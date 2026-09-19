"""Tests for date parsing.

Years of experience is a number Roleva scores against, so these are arithmetic
tests as much as parsing ones. Every format here appears in the corpus.
"""

from __future__ import annotations

from datetime import date

import pytest

from roleva.models.common import DateRange
from roleva.parsing.dates import gaps_between, parse_point, parse_range, total_months


class TestSinglePoints:
    @pytest.mark.parametrize(
        ("text", "year", "month"),
        [
            ("June 2025", 2025, 6),
            ("Jun 2025", 2025, 6),
            ("Dec. 2024", 2024, 12),
            ("September, 2023", 2023, 9),
            ("06/2025", 2025, 6),
            ("2024-01", 2024, 1),
            ("15/07/2021", 2021, 7),
            ("2022", 2022, None),
            ("Summer 2021", 2021, 6),
            ("Winter 2020", 2020, 12),
        ],
    )
    def test_each_written_form_is_parsed(self, text: str, year: int, month: int | None) -> None:
        assert parse_point(text) == (year, month, False)

    @pytest.mark.parametrize("text", ["Present", "current", "Now", "ongoing"])
    def test_present_markers_are_recognised(self, text: str) -> None:
        assert parse_point(text)[2] is True

    def test_a_two_digit_year_is_expanded_sensibly(self) -> None:
        assert parse_point("Jan '23")[0] == 2023
        assert parse_point("Jan '95")[0] == 1995

    def test_unrecognisable_text_yields_nothing(self) -> None:
        assert parse_point("sometime later") == (None, None, False)

    def test_day_first_dates_are_not_read_as_months(self) -> None:
        """15/07/2021 must be July, not month fifteen."""
        assert parse_point("15/07/2021") == (2021, 7, False)


class TestRanges:
    @pytest.mark.parametrize(
        "text",
        [
            "June 2025 - August 2025",
            "June 2025 – August 2025",
            "June 2025 to August 2025",
            "June 2025 until August 2025",
        ],
    )
    def test_every_separator_is_handled(self, text: str) -> None:
        result = parse_range(text)
        assert (result.start_year, result.start_month) == (2025, 6)
        assert (result.end_year, result.end_month) == (2025, 8)

    def test_a_current_role_is_marked_current(self) -> None:
        result = parse_range("Jan 2023 - Present")
        assert result.is_current is True
        assert result.start_year == 2023

    def test_a_single_date_becomes_a_point_range(self) -> None:
        result = parse_range("2022")
        assert result.start_year == 2022
        assert result.end_year == 2022

    def test_the_raw_text_is_kept(self) -> None:
        assert parse_range("June 2025 - August 2025").raw == "June 2025 - August 2025"

    def test_empty_input_is_handled(self) -> None:
        assert parse_range("") == DateRange()

    def test_a_reversed_present_range_is_repaired(self) -> None:
        """ "Present - 2024" is meaningless; the real date is the one given."""
        result = parse_range("Present - 2024")
        assert result.start_year == 2024
        assert result.is_current is False


class TestDurations:
    def test_a_simple_span_is_measured(self) -> None:
        assert parse_range("June 2025 - August 2025").months == 2

    def test_a_year_is_twelve_months(self) -> None:
        assert parse_range("Jan 2023 - Jan 2024").months == 12

    def test_a_current_role_counts_up_to_today(self) -> None:
        months = parse_range(f"Jan {date.today().year} - Present").months
        assert months is not None and months >= 0

    def test_an_unparseable_range_has_no_duration(self) -> None:
        assert parse_range("sometime last year").months is None


class TestTotalExperience:
    def test_separate_periods_add_up(self) -> None:
        ranges = [
            parse_range("Jan 2023 - Jan 2024"),
            parse_range("Jan 2025 - Jul 2025"),
        ]
        assert total_months(ranges) == 18

    def test_overlapping_periods_are_counted_once(self) -> None:
        """Concurrent roles are common on student resumes; adding them up would
        overstate experience."""
        ranges = [
            parse_range("Jan 2023 - Dec 2023"),
            parse_range("Jun 2023 - Dec 2023"),
        ]
        assert total_months(ranges) == 11

    def test_fully_contained_periods_do_not_double_count(self) -> None:
        ranges = [
            parse_range("Jan 2023 - Dec 2024"),
            parse_range("Mar 2023 - Jun 2023"),
        ]
        assert total_months(ranges) == total_months([parse_range("Jan 2023 - Dec 2024")])

    def test_unparseable_entries_are_skipped(self) -> None:
        assert total_months([parse_range("whenever")]) == 0

    def test_nothing_is_zero(self) -> None:
        assert total_months([]) == 0


class TestGaps:
    def test_a_long_gap_is_reported(self) -> None:
        ranges = [
            parse_range("Jan 2022 - Jun 2022"),
            parse_range("Jun 2023 - Dec 2023"),
        ]
        assert gaps_between(ranges)

    def test_a_short_gap_is_not_reported(self) -> None:
        ranges = [
            parse_range("Jan 2023 - Mar 2023"),
            parse_range("May 2023 - Dec 2023"),
        ]
        assert gaps_between(ranges) == []

    def test_a_current_role_never_creates_a_gap(self) -> None:
        ranges = [parse_range("Jan 2020 - Present")]
        assert gaps_between(ranges) == []
