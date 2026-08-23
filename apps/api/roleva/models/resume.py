"""`ResumeDocument` — the canonical structured form of a resume.

This is the most important schema in Roleva. It is deliberately designed to be
**builder-ready**: the future resume builder will edit and render exactly this
object, so v1 stores it in a form a builder could round-trip without migration.

Design rules:
  * Every content item carries a stable `id` so a builder can edit/reorder it.
  * Every text-bearing item carries a `span` so the analyzer can prove evidence.
  * Missing information is `None`. The extractor never guesses or invents.
  * `schema_version` is bumped on any breaking change.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import Field

from roleva.models.common import DateRange, Span, StrictModel

RESUME_SCHEMA_VERSION = 1


def _new_id() -> str:
    return uuid4().hex[:12]


class SectionKind(StrEnum):
    """Canonical section types. Unrecognized headings map to OTHER."""

    CONTACT = "contact"
    SUMMARY = "summary"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    SKILLS = "skills"
    PROJECTS = "projects"
    CERTIFICATIONS = "certifications"
    AWARDS = "awards"
    PUBLICATIONS = "publications"
    VOLUNTEER = "volunteer"
    LANGUAGES = "languages"
    INTERESTS = "interests"
    OTHER = "other"


class SkillOrigin(StrEnum):
    """Where a skill was found. Drives evidence strength during matching:
    a skill demonstrated in a bullet is worth far more than one merely listed."""

    SKILLS_LIST = "skills_list"
    EXPERIENCE_BULLET = "experience_bullet"
    PROJECT_BULLET = "project_bullet"
    SUMMARY = "summary"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    OTHER = "other"


class Bullet(StrictModel):
    id: str = Field(default_factory=_new_id)
    text: str
    span: Span | None = None


class ContactInfo(StrictModel):
    """Populated by deterministic extraction. Feeds the PII redactor — every
    value here is masked before any text is sent to an external LLM."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = Field(default_factory=list)


class ExperienceItem(StrictModel):
    id: str = Field(default_factory=_new_id)
    title: str | None = None
    organization: str | None = None
    location: str | None = None
    dates: DateRange = Field(default_factory=DateRange)
    bullets: list[Bullet] = Field(default_factory=list)
    span: Span | None = None


class EducationItem(StrictModel):
    id: str = Field(default_factory=_new_id)
    degree: str | None = None
    field_of_study: str | None = None
    institution: str | None = None
    location: str | None = None
    dates: DateRange = Field(default_factory=DateRange)
    gpa: str | None = None
    bullets: list[Bullet] = Field(default_factory=list)
    span: Span | None = None


class ProjectItem(StrictModel):
    id: str = Field(default_factory=_new_id)
    name: str | None = None
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)
    dates: DateRange = Field(default_factory=DateRange)
    bullets: list[Bullet] = Field(default_factory=list)
    link: str | None = None
    span: Span | None = None


class SkillMention(StrictModel):
    id: str = Field(default_factory=_new_id)
    raw: str
    canonical: str | None = None
    origin: SkillOrigin = SkillOrigin.OTHER
    span: Span | None = None


class CredentialItem(StrictModel):
    """Certifications, awards, publications — same shape, different section."""

    id: str = Field(default_factory=_new_id)
    title: str
    issuer: str | None = None
    dates: DateRange = Field(default_factory=DateRange)
    span: Span | None = None


class DetectedSection(StrictModel):
    """A heading found in the source document, with its text range."""

    id: str = Field(default_factory=_new_id)
    kind: SectionKind
    heading_text: str | None = None
    order: int = 0
    span: Span | None = None
    heading_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ResumeDocument(StrictModel):
    """The structured resume. Analyzer reads it; the future builder will edit it."""

    schema_version: int = RESUME_SCHEMA_VERSION

    contact: ContactInfo = Field(default_factory=ContactInfo)
    summary: Bullet | None = None
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    skills: list[SkillMention] = Field(default_factory=list)
    certifications: list[CredentialItem] = Field(default_factory=list)
    awards: list[CredentialItem] = Field(default_factory=list)
    publications: list[CredentialItem] = Field(default_factory=list)

    sections: list[DetectedSection] = Field(default_factory=list)

    page_count: int = Field(default=0, ge=0)
    parse_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    parse_warnings: list[str] = Field(default_factory=list)

    def all_bullets(self) -> list[tuple[SkillOrigin, Bullet]]:
        """Every bullet with the origin that determines its evidence weight."""
        out: list[tuple[SkillOrigin, Bullet]] = []
        if self.summary is not None:
            out.append((SkillOrigin.SUMMARY, self.summary))
        for item in self.experience:
            out.extend((SkillOrigin.EXPERIENCE_BULLET, b) for b in item.bullets)
        for proj in self.projects:
            out.extend((SkillOrigin.PROJECT_BULLET, b) for b in proj.bullets)
        for edu in self.education:
            out.extend((SkillOrigin.EDUCATION, b) for b in edu.bullets)
        return out

    def total_experience_months(self) -> int:
        """Summed duration of experience entries. Computed, never generated."""
        return sum(item.dates.months or 0 for item in self.experience)
