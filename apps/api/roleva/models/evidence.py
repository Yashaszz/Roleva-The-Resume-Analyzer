"""Evidence and match results.

The key idea: a match is **not binary**. Where the evidence appears in the
resume determines how much it is worth. A skill demonstrated in a work bullet
with an outcome counts fully; the same skill merely listed in a skills section
counts half. This is what lets Roleva say something no keyword matcher can:

    "You list Docker in your skills section but never show using it."
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from roleva.models.common import Provenance, Span, StrictModel
from roleva.models.resume import SkillOrigin

#: Evidence strength by where the evidence was found. Published in the rubric.
ORIGIN_STRENGTH: dict[SkillOrigin, float] = {
    SkillOrigin.EXPERIENCE_BULLET: 1.00,
    SkillOrigin.PROJECT_BULLET: 0.85,
    SkillOrigin.CERTIFICATION: 0.80,
    SkillOrigin.SUMMARY: 0.60,
    SkillOrigin.SKILLS_LIST: 0.50,
    SkillOrigin.EDUCATION: 0.50,
    SkillOrigin.OTHER: 0.40,
}

#: Partial credit when only a transferable/adjacent skill was found (Vue -> React).
ADJACENT_STRENGTH = 0.40


class MatchStatus(StrEnum):
    MATCHED = "matched"
    PARTIAL = "partial"
    MISSING = "missing"


class Evidence(StrictModel):
    """One piece of support for a requirement, anchored in the resume text.

    Invariant: `span.verify(resume_text)` must pass before this is shown to a
    user. Unverifiable evidence is dropped, which makes hallucinated evidence
    structurally impossible to display.
    """

    span: Span
    origin: SkillOrigin
    provenance: Provenance
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str | None = None

    @property
    def strength(self) -> float:
        return ORIGIN_STRENGTH.get(self.origin, ORIGIN_STRENGTH[SkillOrigin.OTHER])


class RequirementMatch(StrictModel):
    """The resolved outcome for a single JD requirement."""

    requirement_id: str
    status: MatchStatus
    #: 0.0-1.0. Multiplied by the requirement's priority weight when scoring.
    strength: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)
    is_adjacent: bool = False
    #: Set for quantified requirements, e.g. "3+ years" -> actual months found.
    observed_months: int | None = Field(default=None, ge=0)
    explanation: str | None = None

    @property
    def matched(self) -> bool:
        return self.status is MatchStatus.MATCHED


class MatchReport(StrictModel):
    matches: list[RequirementMatch] = Field(default_factory=list)
    #: Resume content with no counterpart in the JD — useful for trimming.
    unmatched_resume_skills: list[str] = Field(default_factory=list)
    llm_adjudicated_count: int = 0

    def by_status(self, status: MatchStatus) -> list[RequirementMatch]:
        return [m for m in self.matches if m.status is status]
