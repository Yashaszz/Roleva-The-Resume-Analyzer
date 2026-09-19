"""Recommendations — what to fix, ranked by what fixing it is worth.

Generated from the analysis, not from a model. Every recommendation traces to
something already computed: a requirement with no evidence, an ATS finding, a
writing metric below target. The model is never asked what the user should do,
because the answer is already in the data and a generated answer would be
unfalsifiable.

Ranking is by **measured projected gain**, which removes the need for a hand-
written priority order. It also produces the right behaviour for free: when the
must-have gate is capping the score, fixing a gated requirement is worth far more
than anything below the cap, so those recommendations rise to the top on their
own arithmetic rather than because someone special-cased them.

One deliberate exception: proofreading fixes carry a gain of zero, because
spelling is not scored. They are still shown, low in the list, labelled as
affecting the reader rather than the number. Silently dropping them would be
hiding a real problem; ranking them by a gain they do not have would be a lie.
"""

from __future__ import annotations

from dataclasses import dataclass

from roleva.advice.impact import (
    ScoringInputs,
    project_ats_fix,
    project_metric_fix,
    project_requirement,
)
from roleva.models.evidence import MatchStatus
from roleva.models.job import Priority
from roleva.models.report import Recommendation, Severity
from roleva.models.resume import SkillOrigin
from roleva.models.scoring import ScoreReport
from roleva.quality.proofread import FlagSeverity, ProofreadReport

#: The user asked for a short, actionable list. Seven is where a list stops
#: reading as priorities and starts reading as a backlog.
MAX_RECOMMENDATIONS = 6

#: Strength a skill reaches when it is only listed, from ORIGIN_STRENGTH.
LISTED_ONLY_STRENGTH = 0.5


@dataclass
class _Candidate:
    recommendation: Recommendation
    gain: float
    #: Identity for deduplication.
    key: tuple[str, str]
    #: Lower sorts first among equal gains.
    tier: int


def _requirement_candidates(inputs: ScoringInputs, baseline: ScoreReport) -> list[_Candidate]:
    by_id = {match.requirement_id: match for match in inputs.matches.matches}
    out: list[_Candidate] = []

    for requirement in inputs.job.requirements:
        match = by_id.get(requirement.id)
        status = match.status if match else MatchStatus.MISSING
        if status is MatchStatus.MATCHED and match and match.strength >= 0.99:
            continue

        projection = project_requirement(inputs, requirement.id, baseline=baseline)
        if not projection.is_meaningful:
            continue

        listed_only = bool(
            match
            and match.evidence
            and all(
                evidence.origin in {SkillOrigin.SKILLS_LIST, SkillOrigin.OTHER}
                for evidence in match.evidence
            )
        )

        if listed_only:
            title = f"Show where you used {requirement.text}"
            detail = (
                f"{requirement.text} appears in your skills list, but no bullet shows you "
                "using it. A reader cannot tell whether you have used it once or for years. "
                "Add it to a bullet that describes what you built and what happened."
            )
        elif status is MatchStatus.MISSING:
            title = f"Address the missing requirement: {requirement.text}"
            detail = (
                f"This job asks for {requirement.text} and nothing in your resume "
                "mentions it. If you have the experience, add the bullet that shows it. "
                "If you do not, this is the gap to close before applying."
            )
        else:
            title = f"Strengthen the evidence for {requirement.text}"
            detail = (
                f"Your evidence for {requirement.text} is indirect. A bullet that names it "
                "explicitly, with an outcome, would remove the doubt."
            )

        severity = (
            Severity.HIGH
            if requirement.priority is Priority.MUST
            else Severity.MEDIUM
            if requirement.priority is Priority.STRONG
            else Severity.LOW
        )

        out.append(
            _Candidate(
                recommendation=Recommendation(
                    id=f"req:{requirement.id}",
                    title=title,
                    detail=detail,
                    severity=severity,
                    projected_gain=projection.gain,
                    related_requirement_ids=[requirement.id],
                ),
                gain=projection.gain,
                key=("requirement", requirement.id),
                tier=0,
            )
        )

    return out


def _ats_candidates(inputs: ScoringInputs, baseline: ScoreReport) -> list[_Candidate]:
    out: list[_Candidate] = []
    seen: set[str] = set()

    for finding in inputs.ats.findings:
        if finding.rule_id.value in seen:
            continue  # one recommendation per rule, however many times it fired
        seen.add(finding.rule_id.value)

        projection = project_ats_fix(inputs, finding.rule_id, baseline=baseline)
        if not projection.is_meaningful:
            continue

        out.append(
            _Candidate(
                recommendation=Recommendation(
                    id=f"ats:{finding.rule_id.value}",
                    title=finding.title,
                    detail=f"{finding.detail} {finding.fix}",
                    severity=Severity.HIGH if finding.deduction >= 15 else Severity.MEDIUM,
                    projected_gain=projection.gain,
                ),
                gain=projection.gain,
                key=("ats", finding.rule_id.value),
                tier=1,
            )
        )

    return out


def _metric_candidates(inputs: ScoringInputs, baseline: ScoreReport) -> list[_Candidate]:
    out: list[_Candidate] = []

    for metric in inputs.metrics.failing:
        projection = project_metric_fix(inputs, metric.key, baseline=baseline)
        if not projection.is_meaningful:
            continue

        out.append(
            _Candidate(
                recommendation=Recommendation(
                    id=f"metric:{metric.key}",
                    title=f"Improve: {metric.label.lower()}",
                    detail=metric.detail,
                    severity=Severity.MEDIUM,
                    projected_gain=projection.gain,
                ),
                gain=projection.gain,
                key=("metric", metric.key),
                tier=2,
            )
        )

    return out


def _proofread_candidate(report: ProofreadReport | None) -> _Candidate | None:
    """One recommendation for all spelling and punctuation errors combined.

    Combined rather than one per typo: six separate entries for six typos would
    crowd out the requirement gaps that actually decide the application.
    """
    if report is None:
        return None
    errors = [flag for flag in report.flags if flag.severity is FlagSeverity.ERROR]
    if not errors:
        return None

    examples = ", ".join(f'"{flag.found}"' for flag in errors[:3])
    return _Candidate(
        recommendation=Recommendation(
            id="writing:proofread",
            title=f"Fix {len(errors)} spelling and punctuation error(s)",
            detail=(
                f"Found {examples}. These do not affect your score — Roleva does not "
                "score spelling — but a reader who spots one reads the rest more "
                "sceptically."
            ),
            severity=Severity.MEDIUM,
            projected_gain=0.0,
        ),
        gain=0.0,
        key=("writing", "proofread"),
        tier=3,
    )


def _dedupe(candidates: list[_Candidate]) -> list[_Candidate]:
    """Drop repeats by source key, then by title.

    Two sources can describe the same fix — a missing requirement and a failing
    metric both pointing at the same absent bullet — and the same instruction
    twice reads as a broken tool.
    """
    seen_keys: set[tuple[str, str]] = set()
    seen_titles: set[str] = set()
    unique: list[_Candidate] = []

    for candidate in candidates:
        title = candidate.recommendation.title.strip().lower()
        if candidate.key in seen_keys or title in seen_titles:
            continue
        seen_keys.add(candidate.key)
        seen_titles.add(title)
        unique.append(candidate)

    return unique


def build(
    inputs: ScoringInputs,
    *,
    baseline: ScoreReport | None = None,
    proofread_report: ProofreadReport | None = None,
    limit: int = MAX_RECOMMENDATIONS,
) -> list[Recommendation]:
    """The ranked, capped recommendation list.

    Pure and deterministic: no model, no network. The same analysis always
    yields the same advice in the same order.
    """
    base = baseline or inputs.score()

    candidates = (
        _requirement_candidates(inputs, base)
        + _ats_candidates(inputs, base)
        + _metric_candidates(inputs, base)
    )

    proofreading = _proofread_candidate(proofread_report)
    if proofreading is not None:
        candidates.append(proofreading)

    # Highest measured gain first. Tier and title break ties reproducibly, so
    # two runs never disagree about the order of two equally valuable fixes.
    candidates.sort(
        key=lambda candidate: (
            -candidate.gain,
            candidate.tier,
            candidate.recommendation.title,
        )
    )

    return [candidate.recommendation for candidate in _dedupe(candidates)[:limit]]


def total_available_gain(recommendations: list[Recommendation]) -> float:
    """Sum of the individual gains, for the "up to +N points" headline.

    Explicitly an upper bound, not a promise: the projections are each measured
    against the same baseline, so applying two fixes that lift the same cap does
    not add up. The UI must present this as "up to", and the report says so.
    """
    return round(sum(recommendation.projected_gain for recommendation in recommendations), 1)
