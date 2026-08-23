"""Job description model — requirements extracted from the target JD.

Priority weighting drives the Job Match score, so it is never left purely to the
LLM: the model proposes a priority, and deterministic cue rules
(`"required"`, `"preferred"`, title mentions, repetition) override it.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import Field

from roleva.models.common import Provenance, Span, StrictModel

JD_SCHEMA_VERSION = 1


def _new_id() -> str:
    return uuid4().hex[:12]


class RequirementCategory(StrEnum):
    HARD_SKILL = "hard_skill"
    TOOL = "tool"
    SOFT_SKILL = "soft_skill"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    DOMAIN = "domain"
    RESPONSIBILITY = "responsibility"


class Priority(StrEnum):
    MUST = "must"
    STRONG = "strong"
    NICE = "nice"


#: Weights used by the scoring engine. Published in the methodology page.
PRIORITY_WEIGHT: dict[Priority, float] = {
    Priority.MUST: 3.0,
    Priority.STRONG: 2.0,
    Priority.NICE: 1.0,
}


class Seniority(StrEnum):
    INTERN = "intern"
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"
    UNKNOWN = "unknown"


class Quantifier(StrictModel):
    """A numeric threshold attached to a requirement, e.g. "3+ years"."""

    years: float | None = Field(default=None, ge=0)
    raw: str | None = None


class Requirement(StrictModel):
    id: str = Field(default_factory=_new_id)
    text: str
    canonical: str | None = None
    category: RequirementCategory
    priority: Priority
    priority_source: Provenance = Provenance.EXTRACTED
    quantifier: Quantifier | None = None
    mention_count: int = Field(default=1, ge=1)
    span: Span | None = None

    @property
    def weight(self) -> float:
        return PRIORITY_WEIGHT[self.priority]


class JobTarget(StrictModel):
    """A parsed job description."""

    schema_version: int = JD_SCHEMA_VERSION

    title: str | None = None
    company: str | None = None
    role_family: str = "general"
    seniority: Seniority = Seniority.UNKNOWN
    requirements: list[Requirement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def by_priority(self, priority: Priority) -> list[Requirement]:
        return [r for r in self.requirements if r.priority is priority]

    @property
    def total_weight(self) -> float:
        return sum(r.weight for r in self.requirements)
