"""The whole pipeline, over the whole corpus.

Every other test checks one stage. This one checks that they fit together: that
the structurer's output is what the matcher expects, that spans survive being
handed between four modules, and that a report comes out the other end with
every number the frontend is going to render.

It runs **offline**, against a fake provider plugged into the real `LlmClient`.
That is deliberate: the client's schema validation, repair retry, budget
accounting and failover are part of what needs testing, so the seam is placed at
the vendor boundary rather than above it. What the fake does not test is whether
a real model returns sensible content — that is Gate 5's live test, which needs a
key and is skipped without one.

The corpus is the adversarial one: two-column layouts, hidden white text, a
prompt-injection attempt, spaced-capital headings, a scanned image, an encrypted
file. A pipeline that only works on the tidy resume is a pipeline that works for
nobody.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

from roleva.api.errors import RolevaError
from roleva.config import Settings
from roleva.llm.budget import DailyBudget, InMemoryUsageStore
from roleva.llm.client import LlmClient
from roleva.models.report import AnalysisStatus, ProgressEvent, Stage
from roleva.orchestration.pipeline import AnalysisRequest, Pipeline

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "fixtures"
RESUMES = FIXTURES / "resumes"
JDS = FIXTURES / "jds"

#: Resumes the validator is supposed to refuse. They are exercised separately:
#: the point of those cases is the written rejection, not a report.
REJECTED = {
    "encrypted.pdf",
    "not-really-a-pdf.pdf",
    "scanned-image.pdf",
    "too-many-pages.pdf",
    "empty-pages.pdf",
}


def _manifest() -> dict[str, Any]:
    raw = (RESUMES / "manifest.yaml").read_text(encoding="utf-8")
    loaded: dict[str, Any] = yaml.safe_load(raw) or {}
    return loaded


def _analysable() -> list[Path]:
    return sorted(p for p in RESUMES.glob("*.pdf") if p.name not in REJECTED)


def _job_description() -> str:
    return (JDS / "backend-entry-years.txt").read_text(encoding="utf-8")


class FakeProvider:
    """A vendor that answers plausibly and identically every time.

    The responses are shaped by which prompt arrives, because the pipeline makes
    four different calls through one interface. Keyed on the rules text rather
    than on call order, so a change to the pipeline's sequencing does not
    silently start feeding requirement JSON to the structurer.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.embed_calls = 0

    async def generate_json(
        self,
        *,
        prompt: str,
        model: str,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        timeout: float = 25.0,
    ) -> str:
        if "<resume>" in prompt and "rate how a resume is written" in prompt.lower():
            self.calls.append("rubric")
            return json.dumps(
                {
                    "clarity": 4,
                    "impact": 3,
                    "specificity": 4,
                    "professionalism": 4,
                    "relevance": 4,
                    "notes": ["Bullets are clear but several describe duties."],
                }
            )

        if "rewrite" in prompt.lower() and "<bullets>" in prompt:
            self.calls.append("advice")
            # Grounded rewrites: no number, employer or technology the original
            # did not already contain.
            return json.dumps(
                {
                    "rewrites": [
                        {
                            "index": index,
                            "suggestion": "Maintained the system described above",
                            "reasons": ["Opens with a verb"],
                        }
                        for index in range(1, 6)
                    ]
                }
            )

        if "<job>" in prompt:
            self.calls.append("requirements")
            return json.dumps(
                {
                    "title": "Backend Engineer",
                    "company": "Example",
                    "role_family": "backend_engineering",
                    "seniority": "entry",
                    "requirements": [
                        {"text": "Python", "category": "hard_skill", "priority": "must"},
                        {"text": "Django", "category": "hard_skill", "priority": "strong"},
                        {"text": "Kubernetes", "category": "hard_skill", "priority": "nice"},
                    ],
                }
            )

        if "adjudicat" in prompt.lower() or "verdict" in prompt.lower():
            self.calls.append("adjudicate")
            return json.dumps({"decisions": []})

        # Anything else is the structurer.
        self.calls.append("structure")
        return json.dumps(
            {
                "summary": "",
                "experience": [
                    {
                        "title": "Software Engineer Intern",
                        "organization": "Zentara Technologies",
                        "location": "",
                        "dates": "Jun 2024 - Jun 2025",
                        "bullets": [
                            "Built a Django service handling 40,000 requests per day",
                            "Worked on various tasks as needed",
                        ],
                    }
                ],
                "education": [],
                "projects": [],
                "skills": ["Python", "Django", "PostgreSQL"],
                "certifications": [],
            }
        )

    async def embed(self, *, texts: list[str], model: str) -> list[list[float]]:
        self.embed_calls += 1
        # Deterministic pseudo-vectors: identical text always embeds identically,
        # which is what the cache and the reproducibility claim both rely on.
        return [[float((hash(text) >> shift) % 97) / 97 for shift in range(8)] for text in texts]


def _pipeline(provider: FakeProvider, emit: Any = None) -> Pipeline:
    settings = Settings(_env_file=None, gemini_api_key="not-used-by-the-fake")
    client = LlmClient(
        provider,  # type: ignore[arg-type]
        settings,
        DailyBudget(InMemoryUsageStore(), settings.llm_max_rpd),
    )
    return Pipeline(client=client, settings=settings, emit=emit)


async def _run(path: Path, *, emit: Any = None) -> Any:
    provider = FakeProvider()
    pipeline = _pipeline(provider, emit=emit)
    outcome = await pipeline.run(
        AnalysisRequest(
            analysis_id=uuid.uuid4().hex,
            pdf_bytes=path.read_bytes(),
            job_description=_job_description(),
            filename=path.name,
            user_id="u1",
        )
    )
    return outcome, provider


class TestTheCorpusRunsEndToEnd:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", _analysable(), ids=lambda p: p.name)
    async def test_every_analysable_resume_produces_a_report(self, path: Path) -> None:
        outcome, _ = await _run(path)
        report = outcome.report

        assert report.status in {AnalysisStatus.COMPLETE, AnalysisStatus.PARTIAL}
        assert 0 <= report.scores.overall.value <= 100
        assert report.verdict.strip()
        assert report.rubric_version
        # Every score must expand to something, or the report cannot explain
        # itself and the product's central claim is broken.
        assert report.scores.job_match.components

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", sorted(REJECTED), ids=lambda n: n)
    async def test_rejected_files_fail_with_a_written_message(self, name: str) -> None:
        provider = FakeProvider()
        pipeline = _pipeline(provider)

        with pytest.raises(RolevaError) as caught:
            await pipeline.run(
                AnalysisRequest(
                    analysis_id="a1",
                    pdf_bytes=(RESUMES / name).read_bytes(),
                    job_description=_job_description(),
                    filename=name,
                )
            )

        # The user gets a sentence telling them what to do, not a stack trace.
        assert caught.value.message[0].isupper()
        assert caught.value.message.rstrip().endswith((".", "!"))
        # And nothing was sent to the model for a file we could not open.
        assert provider.calls == []


class TestEvidenceSurvivesTheWholePipeline:
    @pytest.mark.asyncio
    async def test_every_displayed_span_verifies_against_the_resume_text(self) -> None:
        """The anti-hallucination guarantee, checked at the end rather than the
        middle: whatever the stages did to the offsets, the quotes still match."""
        outcome, _ = await _run(RESUMES / "single-column-classic.pdf")

        checked = 0
        for match in outcome.report.matches.matches:
            for evidence in match.evidence:
                assert evidence.span.verify(outcome.resume_text), evidence.span.text
                checked += 1

        assert checked > 0, "no evidence was produced, so nothing was proved"

    @pytest.mark.asyncio
    async def test_no_suggestion_invents_a_fact(self) -> None:
        from roleva.advice import grounding

        outcome, _ = await _run(RESUMES / "single-column-classic.pdf")
        for suggestion in outcome.report.bullet_suggestions:
            assert grounding.check(
                original=suggestion.original, suggestion=suggestion.suggestion
            ).grounded


class TestTheFreeTierBudget:
    @pytest.mark.asyncio
    async def test_an_analysis_stays_within_six_model_calls(self) -> None:
        """The constraint the whole architecture is shaped around."""
        outcome, _ = await _run(RESUMES / "two-column-sidebar.pdf")
        assert outcome.llm_calls <= 6

    @pytest.mark.asyncio
    async def test_embeddings_are_batched_into_one_call(self) -> None:
        _, provider = await _run(RESUMES / "single-column-classic.pdf")
        assert provider.embed_calls <= 1


class TestProgressEvents:
    @pytest.mark.asyncio
    async def test_progress_runs_forward_and_finishes_at_a_hundred(self) -> None:
        events: list[ProgressEvent] = []

        async def emit(event: ProgressEvent) -> None:
            events.append(event)

        await _run(RESUMES / "single-column-classic.pdf", emit=emit)

        percentages = [event.percent for event in events]
        assert percentages == sorted(percentages)
        assert events[-1].stage is Stage.DONE
        assert events[-1].percent == 100
        assert all(event.message.strip() for event in events)

    @pytest.mark.asyncio
    async def test_the_score_is_known_before_advice_is_written(self) -> None:
        """So the progress screen can show the number while suggestions land."""
        events: list[ProgressEvent] = []

        async def emit(event: ProgressEvent) -> None:
            events.append(event)

        await _run(RESUMES / "single-column-classic.pdf", emit=emit)

        advice = next(event for event in events if event.stage is Stage.WRITING_ADVICE)
        assert advice.partial is not None
        assert "overall" in advice.partial


class TestDeterminism:
    @pytest.mark.asyncio
    async def test_the_same_inputs_produce_the_same_scores(self) -> None:
        """Gate 5's reproducibility criterion, through the full pipeline."""
        path = RESUMES / "single-column-classic.pdf"
        values = set()
        for _ in range(3):
            outcome, _ = await _run(path)
            values.add(
                (
                    outcome.report.scores.overall.value,
                    outcome.report.scores.job_match.value,
                    outcome.report.scores.quality.value,
                    outcome.report.scores.ats.value,
                )
            )
        assert len(values) == 1


class TestInjectionAttempt:
    @pytest.mark.asyncio
    async def test_instructions_hidden_in_a_resume_do_not_become_instructions(self) -> None:
        """The corpus file contains text telling the model to score it 100."""
        outcome, _ = await _run(RESUMES / "injection-attempt.pdf")
        # The score comes from the engine, which never reads the document's
        # prose. An injection can at most influence extraction.
        assert outcome.report.scores.overall.value < 100


class TestTheManifestMatchesTheCorpus:
    def test_every_pdf_is_described(self) -> None:
        """A fixture nobody described is a fixture nobody can interpret."""
        manifest = _manifest()
        described = {entry["file"] for entry in manifest.get("fixtures", [])}
        actual = {p.name for p in RESUMES.glob("*.pdf")}
        assert actual <= described, actual - described
