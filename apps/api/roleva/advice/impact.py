"""Projected gain — what a fix is actually worth, in points.

Every recommendation Roleva shows carries a number: *fix this and your score
goes up by about this much.* That number is the difference between advice a user
acts on and advice they skim, so it has to be real.

It is produced the only honest way available: by **re-running the scoring engine
on a modified copy of its own inputs.** Add the missing skill to the match
report, recompute, subtract. Remove the ATS finding, recompute, subtract. Nothing
is estimated, and no model is asked what it thinks a fix is worth — which is the
same rule that governs every other number in the system.

This is possible only because the engine is pure. A scorer that touched the
network or a clock could not be run twenty times on hypothetical inputs inside a
single request, and the projected gains would have had to be guessed.

One consequence worth stating: because the must-have gate caps the overall score,
the projected gain for a missing must-have is often much larger than its weight
suggests. That is correct. Fixing the one thing that lifts a cap really is worth
more than fixing three things underneath it.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from roleva.models.ats import AtsReport, AtsRuleId
from roleva.models.evidence import MatchReport, MatchStatus
from roleva.models.job import JobTarget
from roleva.models.scoring import ScoreReport
from roleva.quality.metrics import MetricsReport
from roleva.scoring.engine import RubricJudgement, compute

#: A gain smaller than this is noise, and presenting "+0.3 points" as a reason
#: to rewrite a section would be padding the list.
MIN_MEANINGFUL_GAIN = 0.5


@dataclass
class ScoringInputs:
    """Everything the engine needs, kept together so it can be re-scored.

    Holding the inputs rather than the output is what makes projection possible:
    a report cannot be asked what it would have been, but its inputs can.
    """

    job: JobTarget
    matches: MatchReport
    ats: AtsReport
    metrics: MetricsReport
    judgement: RubricJudgement | None = None
    rubric: dict[str, Any] | None = None
    parse_confidence: float = 1.0

    def score(self) -> ScoreReport:
        return compute(
            job=self.job,
            matches=self.matches,
            ats=self.ats,
            metrics=self.metrics,
            judgement=self.judgement,
            rubric=self.rubric,
            parse_confidence=self.parse_confidence,
        )

    def copy(self) -> ScoringInputs:
        """A deep copy, so a hypothetical never mutates the real analysis."""
        return ScoringInputs(
            job=self.job.model_copy(deep=True),
            matches=self.matches.model_copy(deep=True),
            ats=self.ats.model_copy(deep=True),
            metrics=copy.deepcopy(self.metrics),
            judgement=self.judgement,
            rubric=self.rubric,
            parse_confidence=self.parse_confidence,
        )


@dataclass(frozen=True)
class Projection:
    """The measured effect of one hypothetical fix."""

    gain: float
    from_value: float
    to_value: float
    #: Per-score movement, for the UI to show where the gain came from.
    by_kind: dict[str, float] = field(default_factory=dict)

    @property
    def is_meaningful(self) -> bool:
        return self.gain >= MIN_MEANINGFUL_GAIN


def _measure(baseline: ScoreReport, improved: ScoreReport) -> Projection:
    """Difference between two reports, clamped at zero.

    A fix that lowers the score means the hypothetical was built wrong. Showing
    a negative gain would be worse than showing none, so it is clamped and the
    recommendation is filtered out by `is_meaningful`.
    """
    gain = round(max(0.0, improved.overall.value - baseline.overall.value), 1)
    return Projection(
        gain=gain,
        from_value=baseline.overall.value,
        to_value=improved.overall.value,
        by_kind={
            "job_match": round(improved.job_match.value - baseline.job_match.value, 1),
            "quality": round(improved.quality.value - baseline.quality.value, 1),
            "ats": round(improved.ats.value - baseline.ats.value, 1),
        },
    )


def project_requirement(
    inputs: ScoringInputs,
    requirement_id: str,
    *,
    strength: float = 1.0,
    baseline: ScoreReport | None = None,
) -> Projection:
    """What demonstrating this requirement would be worth.

    `strength` is the evidence strength the user would reach. The default of 1.0
    is what a work bullet describing real use earns; 0.5 is what merely adding
    the word to a skills list earns, which is why "list it" is never the advice
    when the requirement is a must-have.
    """
    base = baseline or inputs.score()
    hypothetical = inputs.copy()

    existing = next(
        (m for m in hypothetical.matches.matches if m.requirement_id == requirement_id), None
    )
    if existing is None:
        return Projection(gain=0.0, from_value=base.overall.value, to_value=base.overall.value)

    if existing.strength >= strength:
        return Projection(gain=0.0, from_value=base.overall.value, to_value=base.overall.value)

    existing.strength = strength
    existing.status = MatchStatus.MATCHED if strength > 0.5 else MatchStatus.PARTIAL

    return _measure(base, hypothetical.score())


def project_ats_fix(
    inputs: ScoringInputs,
    rule_id: AtsRuleId,
    *,
    baseline: ScoreReport | None = None,
) -> Projection:
    """What removing this formatting problem would be worth."""
    base = baseline or inputs.score()
    hypothetical = inputs.copy()
    hypothetical.ats.findings = [
        finding for finding in hypothetical.ats.findings if finding.rule_id is not rule_id
    ]
    return _measure(base, hypothetical.score())


def project_metric_fix(
    inputs: ScoringInputs,
    metric_key: str,
    *,
    baseline: ScoreReport | None = None,
) -> Projection:
    """What bringing this writing metric to its target would be worth.

    The hypothetical is the metric exactly at target, not perfect. Projecting
    from a perfect score would inflate every gain and promise the user something
    a realistic edit would not deliver.
    """
    base = baseline or inputs.score()
    hypothetical = inputs.copy()

    metric = hypothetical.metrics.get(metric_key)
    if metric is None or metric.meets_target:
        return Projection(gain=0.0, from_value=base.overall.value, to_value=base.overall.value)

    metric.value = metric.target
    return _measure(base, hypothetical.score())


def project_all_ats(inputs: ScoringInputs, *, baseline: ScoreReport | None = None) -> Projection:
    """What a perfectly formatted version of the same resume would score.

    Used for the headline "clean this up and you reach X" rather than for an
    individual recommendation.
    """
    base = baseline or inputs.score()
    hypothetical = inputs.copy()
    hypothetical.ats.findings = []
    return _measure(base, hypothetical.score())
