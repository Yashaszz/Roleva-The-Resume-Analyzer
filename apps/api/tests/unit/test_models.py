"""Contract tests for the domain models.

These guard the two invariants everything else depends on:
  1. A span only counts as evidence if it genuinely occurs in the source text.
  2. Durations are computed from parsed dates, never supplied by a model.
"""

from __future__ import annotations

import pytest

from roleva.models import (
    Band,
    DateRange,
    Evidence,
    Priority,
    Provenance,
    Requirement,
    RequirementCategory,
    SkillOrigin,
    SourceDoc,
    Span,
    band_for_score,
)

RESUME_TEXT = "Built a Django API serving 40k daily requests."


def _span(start: int, end: int, text: str) -> Span:
    return Span(doc=SourceDoc.RESUME, start=start, end=end, text=text)


class TestSpanVerification:
    def test_accepts_a_span_that_matches_the_source(self) -> None:
        span = _span(8, 14, "Django")
        assert span.verify(RESUME_TEXT) is True

    def test_rejects_text_that_is_not_at_those_offsets(self) -> None:
        span = _span(0, 6, "Django")
        assert span.verify(RESUME_TEXT) is False

    def test_rejects_a_span_running_past_the_end_of_the_document(self) -> None:
        span = _span(40, 500, "requests.")
        assert span.verify(RESUME_TEXT) is False

    def test_rejects_an_inverted_range(self) -> None:
        span = _span(14, 8, "Django")
        assert span.verify(RESUME_TEXT) is False


class TestEvidenceStrength:
    def test_a_bullet_outweighs_a_skills_list_entry(self) -> None:
        in_bullet = Evidence(
            span=_span(8, 14, "Django"),
            origin=SkillOrigin.EXPERIENCE_BULLET,
            provenance=Provenance.LEXICAL,
        )
        in_list = Evidence(
            span=_span(8, 14, "Django"),
            origin=SkillOrigin.SKILLS_LIST,
            provenance=Provenance.LEXICAL,
        )
        assert in_bullet.strength > in_list.strength


class TestDateRange:
    def test_computes_months_across_a_year_boundary(self) -> None:
        dates = DateRange(start_year=2023, start_month=6, end_year=2024, end_month=6)
        assert dates.months == 12

    def test_returns_none_when_the_start_is_unknown(self) -> None:
        assert DateRange(end_year=2024).months is None

    def test_never_returns_a_negative_duration(self) -> None:
        dates = DateRange(start_year=2024, start_month=6, end_year=2023, end_month=1)
        assert dates.months == 0


class TestRequirementWeighting:
    @pytest.mark.parametrize(
        ("priority", "expected"),
        [(Priority.MUST, 3.0), (Priority.STRONG, 2.0), (Priority.NICE, 1.0)],
    )
    def test_priority_maps_to_the_published_weight(
        self, priority: Priority, expected: float
    ) -> None:
        req = Requirement(
            text="Python",
            category=RequirementCategory.HARD_SKILL,
            priority=priority,
        )
        assert req.weight == expected


class TestBands:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (92.0, Band.STRONG),
            (70.0, Band.COMPETITIVE),
            (60.0, Band.NEEDS_WORK),
            (45.0, Band.SIGNIFICANT_GAPS),
            (10.0, Band.NOT_ALIGNED),
        ],
    )
    def test_score_lands_in_the_expected_band(self, value: float, expected: Band) -> None:
        assert band_for_score(value) is expected
