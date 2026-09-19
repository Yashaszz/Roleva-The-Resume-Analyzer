"""Date parsing — deterministic, never delegated to a model.

Years of experience is a number Roleva reports and scores against ("3+ years of
Python"). Language models are unreliable at date arithmetic and will confidently
return a plausible wrong figure, so every date here is parsed by rule and every
duration is computed, not generated.

Resumes write dates in whatever form the writer preferred. The formats below
are the ones that actually appear; anything unrecognised is returned as
`raw` with no parsed values, which is honest and lets the parse-confidence
score account for it.
"""

from __future__ import annotations

import re
from datetime import date
from itertools import pairwise

from roleva.models.common import DateRange

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

#: Words meaning "still there". A present end date is computed from today.
_PRESENT = frozenset(
    {"present", "current", "now", "ongoing", "date", "till date", "to date", "today"}
)

#: Seasons, for "Summer 2021". Mapped to the middle of the season.
_SEASONS = {"spring": 3, "summer": 6, "fall": 9, "autumn": 9, "winter": 12}

#: Separators between the two halves of a range. Includes the dash variants
#: resumes actually use.
_RANGE_SPLIT = re.compile(r"\s*(?:-|–|—|to|until|through|thru)\s*", re.IGNORECASE)

_MONTH_YEAR = re.compile(r"\b(" + "|".join(_MONTHS) + r")\.?\s*,?\s*'?(\d{2,4})\b", re.IGNORECASE)
_SEASON_YEAR = re.compile(r"\b(" + "|".join(_SEASONS) + r")\s*'?(\d{2,4})\b", re.IGNORECASE)
_NUMERIC_MY = re.compile(r"\b(\d{1,2})[/\-.](\d{4})\b")  # 06/2025
_NUMERIC_YM = re.compile(r"\b(\d{4})[/\-.](\d{1,2})\b")  # 2024-01
_NUMERIC_DMY = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")  # 15/07/2021
_YEAR_ONLY = re.compile(r"\b'?(\d{4})\b")
_SHORT_YEAR = re.compile(r"'(\d{2})\b")


def _expand_year(value: int) -> int:
    """Turn a two-digit year into a four-digit one.

    Resumes are about recent history, so '95 is 1995 and '23 is 2023.
    """
    if value >= 100:
        return value
    return 2000 + value if value <= 50 else 1900 + value


def parse_point(text: str) -> tuple[int | None, int | None, bool]:
    """Parse one end of a date range into (year, month, is_present)."""
    cleaned = text.strip().lower().strip(".,;")
    if not cleaned:
        return None, None, False

    if cleaned in _PRESENT or any(word in _PRESENT for word in cleaned.split()):
        return None, None, True

    # Day-month-year first: otherwise "15/07/2021" is read as month 15.
    match = _NUMERIC_DMY.search(cleaned)
    if match:
        return int(match.group(3)), int(match.group(2)), False

    match = _MONTH_YEAR.search(cleaned)
    if match:
        return _expand_year(int(match.group(2))), _MONTHS[match.group(1).lower()], False

    match = _SEASON_YEAR.search(cleaned)
    if match:
        return _expand_year(int(match.group(2))), _SEASONS[match.group(1).lower()], False

    match = _NUMERIC_MY.search(cleaned)
    if match and 1 <= int(match.group(1)) <= 12:
        return int(match.group(2)), int(match.group(1)), False

    match = _NUMERIC_YM.search(cleaned)
    if match and 1 <= int(match.group(2)) <= 12:
        return int(match.group(1)), int(match.group(2)), False

    match = _YEAR_ONLY.search(cleaned)
    if match:
        return int(match.group(1)), None, False

    match = _SHORT_YEAR.search(cleaned)
    if match:
        return _expand_year(int(match.group(1))), None, False

    return None, None, False


def parse_range(text: str) -> DateRange:
    """Parse "June 2025 - August 2025", "2022 – Present", "Summer 2021" and the
    other forms resumes actually use."""
    raw = text.strip()
    if not raw:
        return DateRange()

    parts = _RANGE_SPLIT.split(raw, maxsplit=1)

    if len(parts) == 2 and parts[1].strip():
        start_year, start_month, start_present = parse_point(parts[0])
        end_year, end_month, end_present = parse_point(parts[1])

        # "Present - 2024" is meaningless; a present marker only ends a range.
        if start_present and not end_present:
            start_year, start_month = end_year, end_month
            end_year, end_month, end_present = None, None, False

        return DateRange(
            start_year=start_year,
            start_month=start_month,
            end_year=None if end_present else end_year,
            end_month=None if end_present else end_month,
            is_current=end_present,
            raw=raw,
        )

    # A single point. "Summer 2021" describes a period, not an instant, but
    # without an end date the safest reading is a single month.
    year, month, present = parse_point(raw)
    return DateRange(
        start_year=year,
        start_month=month,
        end_year=None if present else year,
        end_month=None if present else month,
        is_current=present,
        raw=raw,
    )


def total_months(ranges: list[DateRange]) -> int:
    """Summed duration, with overlapping periods counted once.

    Concurrent roles — an internship during a degree, two part-time jobs — are
    common on student resumes, and adding them up would overstate experience.
    """
    intervals: list[tuple[int, int]] = []
    for item in ranges:
        if item.start_year is None:
            continue
        start = item.start_year * 12 + (item.start_month or 1)
        if item.is_current:
            today = date.today()
            end = today.year * 12 + today.month
        elif item.end_year is not None:
            end = item.end_year * 12 + (item.end_month or 12)
        else:
            continue
        if end >= start:
            intervals.append((start, end))

    if not intervals:
        return 0

    intervals.sort()
    merged: list[list[int]] = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    return sum(end - start for start, end in merged)


def gaps_between(ranges: list[DateRange], *, minimum_months: int = 6) -> list[tuple[int, int]]:
    """Gaps between consecutive periods, as (months, year the gap started).

    Reported factually and never speculated about: a gap has many explanations,
    almost none of which are Roleva's business.
    """
    intervals: list[tuple[int, int]] = []
    for item in ranges:
        if item.start_year is None or item.is_current:
            continue
        if item.end_year is None:
            continue
        intervals.append(
            (
                item.start_year * 12 + (item.start_month or 1),
                item.end_year * 12 + (item.end_month or 12),
            )
        )

    intervals.sort()
    gaps: list[tuple[int, int]] = []
    for (_, earlier_end), (later_start, _) in pairwise(intervals):
        months = later_start - earlier_end
        if months >= minimum_months:
            gaps.append((months, earlier_end // 12))
    return gaps
