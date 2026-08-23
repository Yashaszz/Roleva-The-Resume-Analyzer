"""Score models.

Architectural invariant: **no value in this module ever originates from an LLM.**
The scoring engine is a pure function of structured inputs, which is what makes
Roleva's scores reproducible, unit-testable, and explainable.

Every score carries the components that produced it, and every component can
point back at the evidence spans behind it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from roleva.models.common import Provenance, StrictModel


class ScoreKind(StrEnum):
    OVERALL = "overall"
    JOB_MATCH = "job_match"
    ATS = "ats"
    QUALITY = "quality"


class Band(StrEnum):
    STRONG = "strong"
    COMPETITIVE = "competitive"
    NEEDS_WORK = "needs_work"
    SIGNIFICANT_GAPS = "significant_gaps"
    NOT_ALIGNED = "not_aligned"


BAND_THRESHOLDS: list[tuple[float, Band]] = [
    (85.0, Band.STRONG),
    (70.0, Band.COMPETITIVE),
    (55.0, Band.NEEDS_WORK),
    (40.0, Band.SIGNIFICANT_GAPS),
    (0.0, Band.NOT_ALIGNED),
]


def band_for_score(value: float) -> Band:
    for threshold, band in BAND_THRESHOLDS:
        if value >= threshold:
            return band
    return Band.NOT_ALIGNED


class ScoreComponent(StrictModel):
    """One contributing factor, with its arithmetic exposed."""

    key: str
    label: str
    #: Signed contribution to the parent score, in points.
    contribution: float
    weight: float | None = None
    raw_value: float | None = None
    provenance: Provenance
    detail: str | None = None
    #: Ids of requirements or findings a user can drill into.
    evidence_refs: list[str] = Field(default_factory=list)


class Score(StrictModel):
    kind: ScoreKind
    value: float = Field(ge=0.0, le=100.0)
    band: Band
    components: list[ScoreComponent] = Field(default_factory=list)
    #: Set when a cap was applied (e.g. the must-have gate), so the UI can say so.
    cap_applied: str | None = None
    uncapped_value: float | None = Field(default=None, ge=0.0, le=100.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ExpectedBand(StrictModel):
    """Reference range for a role family + seniority. Curated, not measured —
    always labelled as a "typical range", never as a percentile."""

    kind: ScoreKind
    low: float = Field(ge=0.0, le=100.0)
    high: float = Field(ge=0.0, le=100.0)
    position: str  # "below" | "within" | "above"


class Percentile(StrictModel):
    """True cohort percentile. Only populated once `sample_size` >= 30; below
    that the UI must show nothing rather than a fabricated statistic."""

    kind: ScoreKind
    percentile: float = Field(ge=0.0, le=100.0)
    sample_size: int = Field(ge=30)
    role_family: str
    seniority: str


class ScoreReport(StrictModel):
    overall: Score
    job_match: Score
    ats: Score
    quality: Score

    #: Coverage of `must`-priority requirements, 0.0-1.0. Reported separately
    #: from the headline number because it is what actually decides screening.
    must_coverage: float = Field(ge=0.0, le=1.0)
    overall_coverage: float = Field(ge=0.0, le=1.0)

    expected_bands: list[ExpectedBand] = Field(default_factory=list)
    percentiles: list[Percentile] = Field(default_factory=list)

    rubric_version: str

    def as_dict(self) -> dict[str, Score]:
        return {
            "overall": self.overall,
            "job_match": self.job_match,
            "ats": self.ats,
            "quality": self.quality,
        }
