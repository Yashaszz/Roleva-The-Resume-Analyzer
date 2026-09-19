"""Span location and verification.

This is the mechanism behind Roleva's central promise: every claim shown to a
user points at the exact characters it came from. A model can only report text
that is genuinely in the resume, because anything it invents cannot be located
and is dropped before it reaches the report.

Locating is deliberately forgiving about whitespace and lenient about trailing
punctuation, because a model quoting a bullet will not reproduce PDF spacing
exactly. It is *not* forgiving about content: the words have to be there.
"""

from __future__ import annotations

import re

from roleva.models.common import SourceDoc, Span

#: Whitespace differences are a formatting artifact, not a content difference.
_WHITESPACE = re.compile(r"\s+")

#: Leading bullet markers and trailing punctuation a model may add or drop.
_TRIM = " \t•-–—*·.,;:"

#: Below this similarity a "match" is a different sentence that happens to
#: share words, so it is rejected.
_MIN_TOKEN_OVERLAP = 0.85


def _collapse(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _token_overlap(left: str, right: str) -> float:
    left_tokens = left.lower().split()
    right_tokens = right.lower().split()
    if not left_tokens:
        return 0.0
    shared = sum(1 for token in left_tokens if token in right_tokens)
    return shared / len(left_tokens)


def locate(haystack: str, needle: str, *, doc: SourceDoc = SourceDoc.RESUME) -> Span | None:
    """Find `needle` in `haystack` and return a verified span, or None.

    Three attempts, each more forgiving about formatting but none about
    content:

      1. Exact match.
      2. Match after trimming bullet markers and trailing punctuation.
      3. Match with internal whitespace collapsed, mapped back to real offsets.
    """
    if not needle or not haystack:
        return None

    start = haystack.find(needle)
    if start != -1:
        return Span(doc=doc, start=start, end=start + len(needle), text=needle)

    trimmed = needle.strip(_TRIM)
    if trimmed and trimmed != needle:
        start = haystack.find(trimmed)
        if start != -1:
            return Span(doc=doc, start=start, end=start + len(trimmed), text=trimmed)
    if not trimmed:
        return None

    return _locate_collapsed(haystack, trimmed, doc)


def _locate_collapsed(haystack: str, needle: str, doc: SourceDoc) -> Span | None:
    """Match ignoring whitespace differences, then map back to real offsets.

    A model re-typing a bullet rarely reproduces the exact spacing a PDF
    produced, so this is the case that matters in practice.
    """
    positions: list[int] = []
    collapsed_chars: list[str] = []
    previous_space = False

    for index, char in enumerate(haystack):
        if char.isspace():
            if previous_space or not collapsed_chars:
                continue
            previous_space = True
            collapsed_chars.append(" ")
            positions.append(index)
            continue
        previous_space = False
        collapsed_chars.append(char)
        positions.append(index)

    collapsed = "".join(collapsed_chars)
    target = _collapse(needle)
    if not target:
        return None

    found = collapsed.find(target)
    if found == -1:
        return None

    start = positions[found]
    last = positions[min(found + len(target) - 1, len(positions) - 1)]
    end = last + 1

    # The recovered range must still be the text we were asked for.
    if _token_overlap(target, haystack[start:end]) < _MIN_TOKEN_OVERLAP:
        return None

    return Span(doc=doc, start=start, end=end, text=haystack[start:end])


def verify_all(spans: list[Span], source: str) -> tuple[list[Span], list[Span]]:
    """Split spans into those that check out and those that do not."""
    verified = [span for span in spans if span.verify(source)]
    rejected = [span for span in spans if not span.verify(source)]
    return verified, rejected


def locate_many(
    haystack: str, needles: list[str], *, doc: SourceDoc = SourceDoc.RESUME
) -> tuple[list[tuple[str, Span]], list[str]]:
    """Locate several strings, reporting which could not be found.

    The unfound list is not a failure to be hidden. It is the signal that a
    model produced text the resume does not contain, and it feeds both the
    parse-confidence score and the logs.
    """
    found: list[tuple[str, Span]] = []
    missing: list[str] = []

    for needle in needles:
        span = locate(haystack, needle, doc=doc)
        if span is None:
            missing.append(needle)
        else:
            found.append((needle, span))

    return found, missing
