"""The scoring engine.

**This module is a pure function.** No network, no database, no model, no clock,
no randomness. Given the same inputs it returns the same numbers, every time,
forever. That is not a stylistic preference — it is what makes Roleva's scores
reproducible, unit-testable, explainable, and immune to prompt injection. An
attacker cannot move a number that no model produces.

A lint rule enforces the boundary, and the golden tests fail on any drift.

Every score returned here carries the components that produced it, and every
component points at the evidence behind it. The user can expand any number and
follow it down to a line in their own resume — which is the difference between
a score and an opinion.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from roleva.models.ats import AtsReport
from roleva.models.common import Provenance
from roleva.models.evidence import MatchReport, MatchStatus
from roleva.models.job import JobTarget, Priority
from roleva.models.scoring import (
    Band,
    ExpectedBand,
    Score,
    ScoreComponent,
    ScoreKind,
    ScoreReport,
    band_for_score,
)
from roleva.quality.metrics import MetricsReport

RUBRIC_PATH = Path(__file__).parent / "rubric.yaml"


@lru_cache(maxsize=1)
def load_rubric(path: str | None = None) -> dict[str, Any]:
    """Load the published rubric. Cached: it is a constant at runtime."""
    target = Path(path) if path else RUBRIC_PATH
    data: dict[str, Any] = yaml.safe_load(target.read_text(encoding="utf-8"))
    return data


@dataclass(frozen=True)
class RubricJudgement:
    """The judged portion of quality, on an anchored 1-5 scale.

    Anchored means each level has a written descriptor rather than a vague
    instruction to rate out of five — it is the single largest reducer of
    run-to-run variance in this kind of judgement.
    """

    clarity: int = 3
    impact: int = 3
    specificity: int = 3
    professionalism: int = 3
    relevance: int = 3

    def as_dict(self) -> dict[str, int]:
        return {
            "clarity": self.clarity,
            "impact": self.impact,
            "specificity": self.specificity,
            "professionalism": self.professionalism,
            "relevance": self.relevance,
        }


def _to_percent(level: int) -> float:
    """Map a 1-5 anchored level onto 0-100.

    1 is 0 and 5 is 100, so a mid rating of 3 lands at 50 rather than 60. A
    scale that cannot express "poor" is not a scale.
    """
    return max(0.0, min(100.0, (level - 1) / 4 * 100))


# --------------------------------------------------------------- job match ---


def score_job_match(
    job: JobTarget, matches: MatchReport, rubric: dict[str, Any]
) -> tuple[Score, float, float]:
    """Weighted requirement coverage, with the must-have gate applied.

    Returns the score plus must-have and overall coverage, which are reported
    separately because the headline number alone hides the thing that actually
    decides screening.
    """
    weights = rubric["priority_weights"]
    by_id = {match.requirement_id: match for match in matches.matches}

    components: list[ScoreComponent] = []
    total_weight = 0.0
    earned_weight = 0.0
    must_weight = 0.0
    must_earned = 0.0

    for requirement in job.requirements:
        weight = weights[requirement.priority.value]
        match = by_id.get(requirement.id)
        strength = match.strength if match else 0.0

        total_weight += weight
        earned_weight += weight * strength

        if requirement.priority is Priority.MUST:
            must_weight += weight
            must_earned += weight * strength

        components.append(
            ScoreComponent(
                key=f"requirement:{requirement.id}",
                label=requirement.text,
                contribution=round(weight * strength, 3),
                weight=weight,
                raw_value=round(strength, 3),
                provenance=Provenance.COMPUTED,
                detail=match.explanation if match else "Not found in the resume",
                evidence_refs=[requirement.id],
            )
        )

    if total_weight == 0:
        empty = Score(
            kind=ScoreKind.JOB_MATCH,
            value=0.0,
            band=Band.NOT_ALIGNED,
            components=[],
            confidence=0.0,
        )
        return empty, 0.0, 0.0

    raw = earned_weight / total_weight * 100
    must_coverage = must_earned / must_weight if must_weight else 1.0
    overall_coverage = earned_weight / total_weight

    capped = raw
    cap_reason: str | None = None
    for gate in rubric["must_have_gate"]:
        if must_coverage < gate["below_coverage"] and capped > gate["cap"]:
            capped = float(gate["cap"])
            cap_reason = (
                f"Capped at {gate['cap']}: you match "
                f"{round(must_coverage * 100)}% of this role's must-have requirements. "
                "Matching optional requirements cannot make up for missing essential ones."
            )

    return (
        Score(
            kind=ScoreKind.JOB_MATCH,
            value=round(capped, 1),
            band=band_for_score(capped),
            components=components,
            cap_applied=cap_reason,
            uncapped_value=round(raw, 1) if cap_reason else None,
        ),
        round(must_coverage, 4),
        round(overall_coverage, 4),
    )


# --------------------------------------------------------------------- ats ---


def score_ats(report: AtsReport, rubric: dict[str, Any]) -> Score:
    """100 minus the deductions, floored at zero."""
    settings = rubric["ats"]
    value = max(float(settings["floor"]), settings["starting_score"] - report.total_deduction)

    components = [
        ScoreComponent(
            key=finding.rule_id.value,
            label=finding.title,
            contribution=-finding.deduction,
            provenance=Provenance.RULE,
            detail=finding.fix,
        )
        for finding in report.findings
    ]

    # A perfect score still needs something behind it. Expanding a 100 and
    # finding an empty panel reads as a bug rather than as good news.
    if not components:
        components.append(
            ScoreComponent(
                key="ats.no_issues",
                label="No formatting problems found",
                contribution=0.0,
                provenance=Provenance.RULE,
                detail=(
                    f"All {report.checks_run} formatting checks passed. "
                    "Nothing here should trip up automated screening."
                ),
            )
        )

    return Score(
        kind=ScoreKind.ATS,
        value=round(value, 1),
        band=band_for_score(value),
        components=components,
    )


# ----------------------------------------------------------------- quality ---


def score_quality(
    metrics: MetricsReport,
    judgement: RubricJudgement | None,
    rubric: dict[str, Any],
) -> Score:
    """Counted metrics and anchored judgement, combined by published weights."""
    split = rubric["quality_split"]
    metric_weights = rubric["metric_weights"]
    rubric_weights = rubric["rubric_weights"]

    components: list[ScoreComponent] = []

    metric_total = 0.0
    metric_weight_used = 0.0
    for metric in metrics.metrics:
        weight = metric_weights.get(metric.key)
        if weight is None:
            continue
        attainment = metric.attainment
        metric_total += attainment * weight
        metric_weight_used += weight

        components.append(
            ScoreComponent(
                key=f"metric:{metric.key}",
                label=metric.label,
                contribution=round(attainment * weight * 100 * split["metrics"], 2),
                weight=weight,
                raw_value=round(metric.value, 3),
                provenance=Provenance.COMPUTED,
                detail=metric.detail,
            )
        )

    metric_score = (metric_total / metric_weight_used * 100) if metric_weight_used else 0.0

    # No judgement means the rubric call failed or was skipped. Scoring on the
    # counted portion alone is better than inventing the rest, and the reduced
    # confidence says so rather than hiding it.
    if judgement is None:
        return Score(
            kind=ScoreKind.QUALITY,
            value=round(metric_score, 1),
            band=band_for_score(metric_score),
            components=components,
            confidence=0.6,
        )

    judged_total = 0.0
    for key, level in judgement.as_dict().items():
        weight = rubric_weights.get(key, 0.0)
        percent = _to_percent(level)
        judged_total += percent * weight

        components.append(
            ScoreComponent(
                key=f"rubric:{key}",
                label=key.replace("_", " ").title(),
                contribution=round(percent * weight * split["rubric"], 2),
                weight=weight,
                raw_value=float(level),
                provenance=Provenance.JUDGED,
                detail=f"Rated {level} of 5",
            )
        )

    value = metric_score * split["metrics"] + judged_total * split["rubric"]

    return Score(
        kind=ScoreKind.QUALITY,
        value=round(value, 1),
        band=band_for_score(value),
        components=components,
    )


# ----------------------------------------------------------------- overall ---


def score_overall(
    job_match: Score,
    quality: Score,
    ats: Score,
    rubric: dict[str, Any],
    must_coverage: float = 1.0,
) -> Score:
    """Weighted combination, with the must-have gate applied again.

    Capping job match alone is not enough. A well-written, cleanly formatted
    resume matching none of a role's essential requirements still scored 75
    overall and was told it was "Competitive" — the exact misleading verdict the
    gate exists to prevent, arriving by a different route. Quality and
    formatting cannot substitute for being able to do the job.
    """
    weights = rubric["overall_weights"]
    raw = (
        job_match.value * weights["job_match"]
        + quality.value * weights["quality"]
        + ats.value * weights["ats"]
    )

    value = raw
    cap_reason: str | None = None
    for gate in rubric["must_have_gate"]:
        if must_coverage < gate["below_coverage"] and value > gate["cap"]:
            value = float(gate["cap"])
            cap_reason = (
                f"Capped at {gate['cap']}: you match "
                f"{round(must_coverage * 100)}% of this role's must-have requirements. "
                "A polished resume cannot make up for missing what the role requires."
            )

    components = [
        ScoreComponent(
            key=part.kind.value,
            label=part.kind.value.replace("_", " ").title(),
            contribution=round(part.value * weights[part.kind.value], 2),
            weight=weights[part.kind.value],
            raw_value=part.value,
            provenance=Provenance.COMPUTED,
            detail=f"{part.value} weighted at {int(weights[part.kind.value] * 100)}%",
        )
        for part in (job_match, quality, ats)
    ]

    return Score(
        kind=ScoreKind.OVERALL,
        value=round(value, 1),
        band=band_for_score(value),
        components=components,
        cap_applied=cap_reason,
        uncapped_value=round(raw, 1) if cap_reason else None,
        confidence=min(job_match.confidence, quality.confidence, ats.confidence),
    )


# ------------------------------------------------------------ expected band ---


def expected_bands(
    scores: dict[ScoreKind, Score],
    *,
    role_family: str,
    seniority: str,
    rubric: dict[str, Any],
) -> list[ExpectedBand]:
    """Compare against a curated reference range.

    Available from the first analysis, unlike percentiles, which need real
    cohort data. Always labelled a typical range and never presented as a
    measured statistic.
    """
    table = rubric["expected_bands"]
    family = table.get(role_family) or table["general"]
    ranges = family.get(seniority) or family.get("entry") or next(iter(family.values()))

    bands: list[ExpectedBand] = []
    for kind in (ScoreKind.JOB_MATCH, ScoreKind.QUALITY, ScoreKind.ATS):
        bounds = ranges.get(kind.value)
        score = scores.get(kind)
        if not bounds or score is None:
            continue

        low, high = float(bounds[0]), float(bounds[1])
        if score.value < low:
            position = "below"
        elif score.value > high:
            position = "above"
        else:
            position = "within"

        bands.append(ExpectedBand(kind=kind, low=low, high=high, position=position))

    return bands


# -------------------------------------------------------------------- entry ---


def compute(
    *,
    job: JobTarget,
    matches: MatchReport,
    ats: AtsReport,
    metrics: MetricsReport,
    judgement: RubricJudgement | None = None,
    rubric: dict[str, Any] | None = None,
    parse_confidence: float = 1.0,
) -> ScoreReport:
    """Compute every score from structured inputs.

    Pure: the only thing that decides the output is what is passed in.
    """
    config = rubric or load_rubric()

    job_match, must_coverage, overall_coverage = score_job_match(job, matches, config)
    ats_score = score_ats(ats, config)
    quality = score_quality(metrics, judgement, config)
    overall = score_overall(job_match, quality, ats_score, config, must_coverage)

    # A shaky parse makes every downstream number less certain, and saying so
    # is more useful than a confident figure built on bad extraction.
    for score in (job_match, quality, ats_score, overall):
        object.__setattr__(score, "confidence", round(min(score.confidence, parse_confidence), 3))

    return ScoreReport(
        overall=overall,
        job_match=job_match,
        ats=ats_score,
        quality=quality,
        must_coverage=must_coverage,
        overall_coverage=overall_coverage,
        expected_bands=expected_bands(
            {
                ScoreKind.JOB_MATCH: job_match,
                ScoreKind.QUALITY: quality,
                ScoreKind.ATS: ats_score,
            },
            role_family=job.role_family,
            seniority=job.seniority.value,
            rubric=config,
        ),
        percentiles=[],
        rubric_version=config["version"],
    )


def summarise_coverage(job: JobTarget, matches: MatchReport) -> dict[str, int]:
    """Counts by status, for the headline the report opens with."""
    return {
        "matched": len(matches.by_status(MatchStatus.MATCHED)),
        "partial": len(matches.by_status(MatchStatus.PARTIAL)),
        "missing": len(matches.by_status(MatchStatus.MISSING)),
        "must_have_total": len(job.by_priority(Priority.MUST)),
    }
