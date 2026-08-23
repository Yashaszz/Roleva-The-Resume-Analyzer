"""ATS findings — 100% deterministic.

No LLM touches this stage. Every check is a measurable fact about the PDF's
layout, fonts, structure, or contact data. Each finding tells the user what is
wrong, where it is, why it matters, and how to fix it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from roleva.models.common import StrictModel


class AtsSeverity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class AtsRuleId(StrEnum):
    MULTI_COLUMN = "ats.multi_column"
    TEXT_IN_TABLE = "ats.text_in_table"
    TEXT_AS_IMAGE = "ats.text_as_image"
    CONTENT_IN_HEADER_FOOTER = "ats.content_in_header_footer"
    NO_STANDARD_SECTIONS = "ats.no_standard_sections"
    MISSING_EXPERIENCE = "ats.missing_experience"
    MISSING_EDUCATION = "ats.missing_education"
    MISSING_EMAIL = "ats.missing_email"
    MISSING_PHONE = "ats.missing_phone"
    UNPARSEABLE_DATES = "ats.unparseable_dates"
    EXOTIC_FONTS = "ats.exotic_fonts"
    HIDDEN_TEXT = "ats.hidden_text"
    INFORMATIVE_GRAPHICS = "ats.informative_graphics"
    EXCESSIVE_LENGTH = "ats.excessive_length"
    SPECIAL_CHARS_IN_HEADERS = "ats.special_chars_in_headers"
    UNPROFESSIONAL_FILENAME = "ats.unprofessional_filename"


class AtsFinding(StrictModel):
    rule_id: AtsRuleId
    severity: AtsSeverity
    #: Points deducted from a starting score of 100.
    deduction: float = Field(ge=0.0, le=100.0)
    title: str
    detail: str
    fix: str
    page: int | None = Field(default=None, ge=1)
    occurrences: int = Field(default=1, ge=1)


class AtsReport(StrictModel):
    findings: list[AtsFinding] = Field(default_factory=list)
    #: True when white-on-white or zero-size text was detected. Such text is
    #: stripped before any LLM call (prompt-injection defense) and surfaced to
    #: the user as a manipulation red flag.
    hidden_text_detected: bool = False
    checks_run: int = 0

    @property
    def total_deduction(self) -> float:
        return sum(f.deduction for f in self.findings)
