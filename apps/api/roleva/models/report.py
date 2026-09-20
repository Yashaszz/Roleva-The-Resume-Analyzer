"""The analysis report — what the API returns and the frontend renders."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from roleva.models.ats import AtsReport
from roleva.models.common import StrictModel
from roleva.models.evidence import MatchReport
from roleva.models.job import JobTarget
from roleva.models.resume import ResumeDocument, SectionKind
from roleva.models.scoring import ScoreReport

REPORT_SCHEMA_VERSION = 1


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"  # some stages failed; report still useful
    FAILED = "failed"


class Stage(StrEnum):
    """Pipeline stages. Names are user-visible in the progress UI, so they
    describe work the user cares about, not internal function names."""

    VALIDATING = "validating"
    EXTRACTING = "extracting"
    STRUCTURING = "structuring"
    READING_JOB = "reading_job"
    MATCHING = "matching"
    CHECKING_ATS = "checking_ats"
    ASSESSING_QUALITY = "assessing_quality"
    SCORING = "scoring"
    WRITING_ADVICE = "writing_advice"
    DONE = "done"


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BulletSuggestion(StrictModel):
    """A concrete improvement for one weak bullet.

    Grounding rule: the suggestion may not introduce facts (numbers, employers,
    technologies) absent from `original`. Violations are regenerated once, then
    dropped.
    """

    bullet_id: str
    original: str
    suggestion: str
    reasons: list[str] = Field(default_factory=list)
    section: SectionKind


class Recommendation(StrictModel):
    id: str
    title: str
    detail: str
    severity: Severity
    #: Estimated points gained if applied — recomputed by the scoring engine,
    #: never guessed by a model. Drives the ordering of the list.
    projected_gain: float = Field(default=0.0, ge=0.0, le=100.0)
    related_requirement_ids: list[str] = Field(default_factory=list)


class SectionFeedback(StrictModel):
    section: SectionKind
    rating: int = Field(ge=1, le=5)
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class AnalysisReport(StrictModel):
    schema_version: int = REPORT_SCHEMA_VERSION

    id: str
    status: AnalysisStatus
    created_at: datetime

    resume: ResumeDocument
    job: JobTarget
    matches: MatchReport
    ats: AtsReport
    scores: ScoreReport

    #: The single sentence the report opens with, at display size. Built from
    #: computed facts, like everything else here.
    headline: str = ""
    verdict: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    section_feedback: list[SectionFeedback] = Field(default_factory=list)
    bullet_suggestions: list[BulletSuggestion] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)

    #: Stamped so any report can be reproduced or explained after a rubric change.
    rubric_version: str
    prompt_version: str
    #: Stages that failed, when status is PARTIAL.
    degraded_stages: list[Stage] = Field(default_factory=list)


class ProgressEvent(StrictModel):
    """One SSE frame. The progress screen is a designed experience, not a
    spinner, so events carry real stage names and optional partial results."""

    analysis_id: str
    stage: Stage
    message: str
    percent: int = Field(ge=0, le=100)
    partial: dict[str, object] | None = None
