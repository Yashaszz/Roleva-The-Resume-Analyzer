"""Primitives shared across every domain model.

The single most important type here is `Span`. Every user-visible claim Roleva
makes must be traceable to a `Span` in the source text. This is the mechanism
behind the product's explainability guarantee and its anti-hallucination check:
if the quoted text is not found verbatim at those offsets, the claim is dropped.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base for all domain models: reject unknown fields, stay immutable-ish."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SourceDoc(StrEnum):
    RESUME = "resume"
    JOB_DESCRIPTION = "job_description"


class Span(StrictModel):
    """A character range in a normalized source document."""

    doc: SourceDoc
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=2000)
    page: int | None = Field(default=None, ge=1)
    section_id: str | None = None

    def verify(self, source_text: str) -> bool:
        """True when `text` genuinely occurs at [start:end] in `source_text`.

        Called on every span before it reaches the user. Failures are dropped
        and logged, never displayed.
        """
        if self.end <= self.start or self.end > len(source_text):
            return False
        return source_text[self.start : self.end] == self.text


class Provenance(StrEnum):
    """How a claim was produced. Rendered in the UI so users can weigh it."""

    RULE = "rule"  # deterministic rule fired
    COMPUTED = "computed"  # arithmetic over other values
    LEXICAL = "lexical"  # exact / alias / fuzzy string match
    SEMANTIC = "semantic"  # embedding similarity
    JUDGED = "judged"  # LLM adjudication
    EXTRACTED = "extracted"  # LLM extraction into a schema


class ConfidenceBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def band_for(confidence: float) -> ConfidenceBand:
    if confidence >= 0.8:
        return ConfidenceBand.HIGH
    if confidence >= 0.5:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


class DateRange(StrictModel):
    """Employment/education dates. Always parsed deterministically in Python —
    never taken from an LLM, which is unreliable at date arithmetic."""

    start_year: int | None = Field(default=None, ge=1950, le=2100)
    start_month: int | None = Field(default=None, ge=1, le=12)
    end_year: int | None = Field(default=None, ge=1950, le=2100)
    end_month: int | None = Field(default=None, ge=1, le=12)
    is_current: bool = False
    raw: str | None = None

    @property
    def months(self) -> int | None:
        """Duration in months, when computable."""
        if self.start_year is None:
            return None
        sm = self.start_month or 1
        if self.is_current:
            from datetime import date

            today = date.today()
            ey, em = today.year, today.month
        elif self.end_year is not None:
            ey, em = self.end_year, self.end_month or 12
        else:
            return None
        return max(0, (ey - self.start_year) * 12 + (em - sm))
