"""The analysis pipeline — every stage, in order, with its failures contained.

This is the only place that knows the shape of a whole analysis. Each stage
module already does its own job well; what happens here is sequencing, isolation
and the one structural decision that makes the free tier survivable:

**The job description is read in parallel with the resume.** Both are LLM calls,
neither depends on the other, and running them concurrently takes roughly six
seconds off an analysis that a user is sitting and watching. Everything after
that point genuinely depends on both, so nothing else is parallelised — inventing
concurrency where a dependency exists would buy nothing and cost correctness.

Progress is emitted through a callback rather than written to a stream directly,
so the same pipeline runs behind a synchronous request, an SSE stream, or a test
that records the events into a list.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from roleva.advice import recommendations as advice_recs
from roleva.advice import summary as verdict
from roleva.advice.impact import ScoringInputs
from roleva.advice.selection import select_weak_bullets
from roleva.advice.writer import write_suggestions
from roleva.ats import rules as ats_rules
from roleva.ats import signals as ats_signals
from roleva.config import Settings, get_settings
from roleva.jd import cleaner as jd_cleaner
from roleva.jd.requirement_extractor import extract_requirements
from roleva.llm.budget import AnalysisBudget
from roleva.llm.client import LlmClient
from roleva.matching.cascade import build_index
from roleva.matching.pipeline import match as run_matching
from roleva.models.ats import AtsReport
from roleva.models.job import JobTarget
from roleva.models.report import AnalysisReport, AnalysisStatus, ProgressEvent, Stage
from roleva.models.resume import ResumeDocument
from roleva.orchestration.stages import (
    StageLog,
    message_for,
    progress_for,
    run_stage,
)
from roleva.parsing import confidence as parse_confidence
from roleva.parsing import contact as contact_parser
from roleva.parsing import normalizer, pdf_reader, sectionizer, validators
from roleva.parsing.structurer import structure_resume
from roleva.quality import metrics as quality_metrics
from roleva.quality import proofread as proofreader
from roleva.quality.rubric_judge import PROMPT_VERSION, describe, judge
from roleva.scoring.engine import RubricJudgement
from roleva.telemetry.logging import get_logger

logger = get_logger(__name__)

#: Called with each progress event. Async so an SSE writer can await on it.
Emitter = Callable[[ProgressEvent], Awaitable[None]]


async def _silent(_: ProgressEvent) -> None:
    """Default emitter: the pipeline works the same with nobody watching."""


@dataclass
class AnalysisRequest:
    analysis_id: str
    pdf_bytes: bytes
    job_description: str
    filename: str | None = None
    user_id: str | None = None


@dataclass
class AnalysisOutcome:
    """The report plus everything the caller needs that is not in it."""

    report: AnalysisReport
    log: StageLog
    #: The engine inputs, kept so projections can be recomputed without a
    #: second analysis — the report alone cannot answer "what if".
    inputs: ScoringInputs | None = None
    resume_text: str = ""
    llm_calls: int = 0
    warnings: list[str] = field(default_factory=list)


class Pipeline:
    """Runs one analysis. Holds no state between runs."""

    def __init__(
        self,
        *,
        client: LlmClient,
        settings: Settings | None = None,
        emit: Emitter | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self.emit = emit or _silent

    async def _announce(self, stage: Stage, partial: dict[str, Any] | None = None) -> None:
        await self.emit(
            ProgressEvent(
                analysis_id=self._analysis_id,
                stage=stage,
                message=message_for(stage),
                percent=progress_for(stage),
                partial=partial,
            )
        )

    async def run(self, request: AnalysisRequest) -> AnalysisOutcome:
        self._analysis_id = request.analysis_id
        log = StageLog()
        budget = AnalysisBudget(max_calls=self.settings.llm_max_calls_per_analysis)
        warnings: list[str] = []

        # --- validate and extract (deterministic, fast, and required) --------
        await self._announce(Stage.VALIDATING)
        parsed = await run_stage(Stage.VALIDATING, log, lambda: self._read_pdf(request.pdf_bytes))
        assert parsed is not None  # REQUIRED stages raise rather than return None
        extracted, stats, signals = parsed

        await self._announce(Stage.EXTRACTING)
        prepared = await run_stage(Stage.EXTRACTING, log, lambda: self._prepare(extracted))
        assert prepared is not None
        normalized, sections, contact = prepared

        # --- resume structuring and job reading, concurrently ----------------
        # Two independent model calls. Running them together is the single
        # largest latency win available, and neither can use the other's output.
        await self._announce(Stage.STRUCTURING)

        async def structure() -> tuple[ResumeDocument, list[str]]:
            return await structure_resume(
                client=self.client,
                text=normalized.text,
                contact=contact,
                sections=sections,
                page_count=stats.page_count,
                analysis_budget=budget,
            )

        async def read_job() -> JobTarget:
            # `clean` raises JD_TOO_SHORT itself, with the written message. A
            # thin-but-acceptable posting is a warning, not a rejection: the
            # user still gets a report, told that it is built on little.
            cleaned = jd_cleaner.clean(request.job_description, self.settings)
            if cleaned.is_thin:
                warnings.append(
                    "This job description is short, so the requirement list may be incomplete."
                )
            return await extract_requirements(
                client=self.client, cleaned=cleaned, analysis_budget=budget
            )

        structured_task = asyncio.create_task(run_stage(Stage.STRUCTURING, log, structure))
        job_task = asyncio.create_task(run_stage(Stage.READING_JOB, log, read_job))

        results = await asyncio.gather(structured_task, job_task, return_exceptions=True)
        structured_result, job_result = results

        # Both are REQUIRED, so either exception ends the analysis. The resume
        # failure is raised first: it is the more specific message of the two.
        for outcome in (structured_result, job_result):
            if isinstance(outcome, BaseException):
                raise outcome

        document, unverified = structured_result  # type: ignore[misc]
        job: JobTarget = job_result  # type: ignore[assignment]
        warnings.extend(unverified)
        await self._announce(Stage.READING_JOB, partial={"requirements": len(job.requirements)})

        # --- matching --------------------------------------------------------
        await self._announce(Stage.MATCHING)
        index = build_index(document, normalized.text)

        async def do_match() -> Any:
            return await run_matching(
                client=self.client,
                job=job,
                document=document,
                index=index,
                resume_text=normalized.text,
                analysis_budget=budget,
            )

        matched = await run_stage(Stage.MATCHING, log, do_match)
        assert matched is not None
        matches, match_stats = matched

        # --- ATS and writing quality ------------------------------------------
        await self._announce(Stage.CHECKING_ATS)
        ats = await run_stage(
            Stage.CHECKING_ATS,
            log,
            lambda: self._check_ats(
                extracted, signals, sections, document, stats, request.filename
            ),
            fallback=AtsReport(checks_run=0),
        )
        assert ats is not None

        await self._announce(Stage.ASSESSING_QUALITY)
        metrics = quality_metrics.measure(document)
        flags = proofreader.proofread(document)

        async def do_judge() -> RubricJudgement:
            judgement, notes = await judge(
                client=self.client,
                text=describe(document),
                contact=contact,
                analysis_budget=budget,
            )
            warnings.extend(notes)
            return judgement

        # Degradable: without it the quality score falls back to its counted
        # half and reports lower confidence, which is a worse report but a true
        # one.
        judgement = await run_stage(Stage.ASSESSING_QUALITY, log, do_judge, fallback=None)

        # --- scoring ----------------------------------------------------------
        await self._announce(Stage.SCORING)
        breakdown = parse_confidence.assess(
            extracted=extracted,
            sections=sections,
            document=document,
            unverified_count=len(unverified),
            reported_count=max(1, len(document.all_bullets())),
        )

        inputs = ScoringInputs(
            job=job,
            matches=matches,
            ats=ats,
            metrics=metrics,
            judgement=judgement,
            parse_confidence=breakdown.score,
        )
        scores = await run_stage(Stage.SCORING, log, lambda: _pure(inputs.score))
        assert scores is not None

        facts = verdict.facts(scores=scores, job=job, matches=matches)
        recommendations = advice_recs.build(inputs, baseline=scores, proofread_report=flags)

        # --- advice ------------------------------------------------------------
        await self._announce(
            Stage.WRITING_ADVICE,
            partial={"overall": scores.overall.value, "band": scores.overall.band.value},
        )
        selected = select_weak_bullets(document)

        async def do_advice() -> Any:
            return await write_suggestions(
                client=self.client,
                selected=selected,
                contexts=_contexts(document),
                contact=contact,
                analysis_budget=budget,
            )

        suggestions = await run_stage(Stage.WRITING_ADVICE, log, do_advice, fallback=None)

        explanation = parse_confidence.explain(breakdown)
        if explanation:
            warnings.append(explanation)

        report = AnalysisReport(
            id=request.analysis_id,
            status=(AnalysisStatus.PARTIAL if log.degraded else AnalysisStatus.COMPLETE),
            created_at=datetime.now(UTC),
            resume=document,
            job=job,
            matches=matches,
            ats=ats,
            scores=scores,
            headline=verdict.headline(facts),
            verdict=verdict.build(facts),
            strengths=verdict.strengths(facts),
            weaknesses=verdict.weaknesses(facts),
            bullet_suggestions=suggestions.suggestions if suggestions else [],
            recommendations=recommendations,
            rubric_version=scores.rubric_version,
            prompt_version=PROMPT_VERSION,
            degraded_stages=log.degraded,
        )

        await self._announce(Stage.DONE)
        logger.info(
            "analysis.complete",
            analysis_id=request.analysis_id,
            overall=scores.overall.value,
            llm_calls=budget.used,
            adjudicated=match_stats.adjudicated,
            **{"duration_ms": log.total_ms},
        )

        return AnalysisOutcome(
            report=report,
            log=log,
            inputs=inputs,
            resume_text=normalized.text,
            llm_calls=budget.used,
            warnings=warnings,
        )

    # ------------------------------------------------------------ stages ---

    async def _read_pdf(self, data: bytes) -> tuple[Any, Any, Any]:
        """Validate, extract text, and collect formatting signals in one open.

        Opening the document once and reading everything out of it keeps the
        PDF bytes in memory for the shortest possible time: they are never
        written to disk and never stored, by explicit product decision.
        """
        with validators.open_validated(data, self.settings) as (doc, stats):
            extracted = pdf_reader.extract(doc)
            signals = ats_signals.collect(doc)
        return extracted, stats, signals

    async def _prepare(self, extracted: Any) -> tuple[Any, Any, Any]:
        normalized = normalizer.normalize(extracted.text)
        sections = sectionizer.sectionize(normalized, extracted)
        contact = contact_parser.extract_contact(normalized.text)
        return normalized, sections, contact

    async def _check_ats(
        self,
        extracted: Any,
        signals: Any,
        sections: Any,
        document: ResumeDocument,
        stats: Any,
        filename: str | None,
    ) -> AtsReport:
        return ats_rules.run(
            ats_rules.AtsContext(
                extracted=extracted,
                signals=signals,
                sections=sections,
                document=document,
                stats=stats,
                filename=filename,
            )
        )


async def _pure(fn: Callable[[], Any]) -> Any:
    """Adapt a synchronous pure function to the async stage runner."""
    return fn()


def _contexts(document: ResumeDocument) -> dict[str, str]:
    """Role title and employer for each bullet.

    Passed to the grounding validator so a rewrite may name the company the
    bullet was already filed under, without that counting as an invention.
    """
    out: dict[str, str] = {}
    for item in document.experience:
        header = " ".join(filter(None, [item.title, item.organization]))
        for bullet in item.bullets:
            out[bullet.id] = header
    for project in document.projects:
        for bullet in project.bullets:
            out[bullet.id] = project.name or ""
    return out
