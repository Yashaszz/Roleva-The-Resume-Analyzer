"""The full four-tier match, in order, with the cost of each tier made visible.

Tiers one and two are free and run for every requirement. Tier three costs one
embedding request, and only for what the first two could not settle. Tier four
costs one model request, and only for what tier three found genuinely
ambiguous.

On a well-matched resume both paid tiers are skipped entirely — the common
case, and the reason a free-tier quota stretches as far as it does.

`MatchStats` records what each tier actually resolved, so the cost model is
measured rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass

from roleva.llm.client import LlmClient
from roleva.matching.adjudicator import adjudicate
from roleva.matching.cascade import (
    ResumeIndex,
    match_all,
    needs_adjudication,
    unmatched_resume_skills,
)
from roleva.matching.semantic import (
    Candidate,
    EmbeddingCache,
    SemanticResult,
    resolve_semantically,
    to_evidence,
)
from roleva.models.evidence import MatchReport, MatchStatus, RequirementMatch
from roleva.models.job import JobTarget
from roleva.models.resume import ResumeDocument
from roleva.parsing.spans import locate


@dataclass
class MatchStats:
    """How many requirements each tier settled, and what that cost."""

    total: int = 0
    deterministic: int = 0
    semantic: int = 0
    adjudicated: int = 0
    unresolved: int = 0
    embedding_calls: int = 0
    llm_calls: int = 0
    cache_hit_rate: float = 0.0

    @property
    def free_share(self) -> float:
        """Share settled without spending a request."""
        return self.deterministic / self.total if self.total else 0.0


def build_candidates(document: ResumeDocument, text: str) -> list[Candidate]:
    """Resume content a requirement could be matched against.

    Bullets rather than skill names: the semantic tier exists for requirements
    phrased as sentences, and only a sentence can match one.
    """
    candidates: list[Candidate] = []

    for origin, bullet in document.all_bullets():
        span = bullet.span or locate(text, bullet.text)
        if span is not None and len(bullet.text.strip()) > 10:
            candidates.append(Candidate(text=bullet.text, origin=origin, span=span))

    return candidates


def _replace(report: MatchReport, match: RequirementMatch) -> None:
    for index, existing in enumerate(report.matches):
        if existing.requirement_id == match.requirement_id:
            report.matches[index] = match
            return


async def match(
    *,
    client: LlmClient,
    job: JobTarget,
    document: ResumeDocument,
    index: ResumeIndex,
    resume_text: str,
    cache: EmbeddingCache | None = None,
    analysis_budget: object = None,
) -> tuple[MatchReport, MatchStats]:
    """Run every requirement through all four tiers."""
    embedding_cache = cache or EmbeddingCache()

    # --- tiers 1 and 2: free ---
    report = match_all(job, index)
    stats = MatchStats(
        total=len(job.requirements),
        deterministic=sum(1 for m in report.matches if m.status is not MatchStatus.MISSING),
    )

    pending = needs_adjudication(job, report)
    if not pending:
        stats.unresolved = sum(1 for m in report.matches if m.status is MatchStatus.MISSING)
        return report, stats

    # --- tier 3: one embedding request ---
    candidates = build_candidates(document, resume_text)
    semantic_results = await resolve_semantically(
        client=client,
        requirements=pending,
        candidates=candidates,
        cache=embedding_cache,
        analysis_budget=analysis_budget,
    )
    stats.embedding_calls = 1 if candidates else 0
    stats.cache_hit_rate = round(embedding_cache.hit_rate, 3)

    by_id = {requirement.id: requirement for requirement in pending}
    ambiguous: list[tuple[object, SemanticResult]] = []

    for result in semantic_results:
        requirement = by_id[result.requirement_id]

        if result.accepted:
            evidence = to_evidence(result)
            if evidence is not None:
                strength = evidence.strength
                _replace(
                    report,
                    RequirementMatch(
                        requirement_id=requirement.id,
                        status=MatchStatus.MATCHED if strength > 0.5 else MatchStatus.PARTIAL,
                        strength=round(strength, 3),
                        evidence=[evidence],
                        explanation="Found in your resume, phrased differently",
                    ),
                )
                stats.semantic += 1
            continue

        if result.ambiguous:
            ambiguous.append((requirement, result))

    if not ambiguous:
        stats.unresolved = sum(1 for m in report.matches if m.status is MatchStatus.MISSING)
        return report, stats

    # --- tier 4: one model request, all ambiguous pairs together ---
    adjudications = await adjudicate(
        client=client,
        pairs=ambiguous,  # type: ignore[arg-type]
        analysis_budget=analysis_budget,
    )
    stats.llm_calls = 1

    for adjudication in adjudications:
        if adjudication.strength <= 0:
            continue
        _replace(
            report,
            RequirementMatch(
                requirement_id=adjudication.requirement_id,
                status=MatchStatus.MATCHED if adjudication.strength > 0.5 else MatchStatus.PARTIAL,
                strength=round(adjudication.strength, 3),
                evidence=[adjudication.evidence] if adjudication.evidence else [],
                explanation=adjudication.reason,
            ),
        )
        stats.adjudicated += 1

    report.llm_adjudicated_count = len(ambiguous)
    report.unmatched_resume_skills = unmatched_resume_skills(index, job)
    stats.unresolved = sum(1 for m in report.matches if m.status is MatchStatus.MISSING)

    return report, stats
