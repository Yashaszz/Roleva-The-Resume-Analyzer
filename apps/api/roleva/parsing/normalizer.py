"""Text normalisation that preserves character offsets.

Extracted PDF text needs cleaning before anything can match against it:
ligatures arrive as single codepoints, so "Profiled" is literally not the string
"Profiled"; five different bullet glyphs mean five different parse paths;
line-wrapped words are split by hyphens; and headings sometimes arrive as
"E X P E R I E N C E".

The difficulty is that every one of those fixes changes the text's length, and
Roleva's whole explainability guarantee rests on being able to point at the
exact characters a claim came from. Cleaning the text while losing the offsets
would trade the product's core promise for tidier strings.

So normalisation is written as a pipeline over `(character, source index)`
pairs. Each step may insert, drop or replace characters, but every character
that survives still knows where it came from — which makes `OffsetMap` correct
by construction rather than by careful bookkeeping.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass

#: Every bullet glyph seen in the wild, mapped to one canonical marker.
_BULLET_GLYPHS = "•·‣⁃▪▫◦●○■□–—*-"
_CANONICAL_BULLET = "•"

#: Characters that vary by producer but mean the same thing.
_CHAR_FIXES = {
    " ": " ",  # non-breaking space
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",  # en dash, outside bullet position
    "—": "-",  # em dash
    "…": "...",
}

#: A line of single characters separated by spaces, e.g. "E X P E R I E N C E".
_SPACED_CAPS = re.compile(r"^(?:[A-Za-z]\s){2,}[A-Za-z]$")

#: A word split across a line break by a hyphen.
_HYPHEN_BREAK = re.compile(r"([A-Za-z]{2,})-\n([a-z]{2,})")


@dataclass
class OffsetMap:
    """Translates positions in normalised text back to the original."""

    #: For each normalised index, the index it came from in the original text.
    sources: list[int]
    original_length: int

    def to_original(self, index: int) -> int:
        if not self.sources:
            return index
        clamped = max(0, min(index, len(self.sources) - 1))
        return self.sources[clamped]

    def span_to_original(self, start: int, end: int) -> tuple[int, int]:
        """Map a normalised range onto the original text.

        The end is taken from the last character actually inside the range, then
        advanced by one, so a range never collapses to zero width or spills into
        the following word.
        """
        if not self.sources:
            return start, end
        first = self.to_original(start)
        last_index = max(start, min(end - 1, len(self.sources) - 1))
        last = self.sources[last_index]
        return first, min(last + 1, self.original_length)


@dataclass
class NormalizedText:
    text: str
    offsets: OffsetMap
    original: str
    #: Headings repaired from letter-spaced form, for the section detector.
    repaired_spaced_lines: int = 0

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        return self.offsets.span_to_original(start, end)

    def verify(self, start: int, end: int) -> str:
        """The original text a normalised range corresponds to."""
        begin, finish = self.original_span(start, end)
        return self.original[begin:finish]


#: A character paired with the index it originated from.
_Pair = tuple[str, int]


def _initial_pairs(text: str) -> list[_Pair]:
    return [(char, index) for index, char in enumerate(text)]


def _apply_unicode(pairs: list[_Pair]) -> list[_Pair]:
    """NFKC, which also expands ligatures.

    A ligature decomposes into several characters, all of which point back at
    the single original codepoint — exactly what a span should do.
    """
    out: list[_Pair] = []
    for char, source in pairs:
        replacement = _CHAR_FIXES.get(char)
        if replacement is None:
            replacement = unicodedata.normalize("NFKC", char)
        for produced in replacement:
            out.append((produced, source))
    return out


def _canonicalise_bullets(pairs: list[_Pair]) -> list[_Pair]:
    """Normalise bullet glyphs, but only where a bullet can occur.

    A dash mid-sentence is punctuation; the same dash at the start of a line is
    a bullet. Position is what distinguishes them.
    """
    out: list[_Pair] = []
    at_line_start = True
    for char, source in pairs:
        if char == "\n":
            at_line_start = True
            out.append((char, source))
            continue
        if char in " \t" and at_line_start:
            out.append((char, source))
            continue
        if at_line_start and char in _BULLET_GLYPHS:
            out.append((_CANONICAL_BULLET, source))
        else:
            out.append((char, source))
        at_line_start = False
    return out


def _join_hyphenated(pairs: list[_Pair]) -> list[_Pair]:
    """Rejoin words split across a line break.

    "auto-\\nmation" is one word. Left alone it matches neither "automation"
    nor anything else, and silently loses a skill.
    """
    text = "".join(char for char, _ in pairs)
    out = list(pairs)
    for match in reversed(list(_HYPHEN_BREAK.finditer(text))):
        hyphen_at = match.start(1) + len(match.group(1))
        del out[hyphen_at : hyphen_at + 2]  # the hyphen and the newline
    return out


def _collapse_whitespace(pairs: list[_Pair]) -> list[_Pair]:
    """Squeeze runs of spaces, and trim trailing space on each line.

    PDF extraction routinely emits several spaces where the layout had one.
    """
    out: list[_Pair] = []
    previous_space = False
    for char, source in pairs:
        if char in " \t":
            if previous_space:
                continue
            previous_space = True
            out.append((" ", source))
            continue
        if char == "\n":
            while out and out[-1][0] == " ":
                out.pop()
            previous_space = False
            out.append((char, source))
            continue
        previous_space = False
        out.append((char, source))

    while out and out[-1][0] == " ":
        out.pop()
    return out


def _repair_spaced_caps(pairs: list[_Pair]) -> tuple[list[_Pair], int]:
    """Close up letter-spaced headings: "E X P E R I E N C E" -> "EXPERIENCE".

    Left alone these match no section-header lexicon, and the document appears
    to have no sections at all.
    """
    out: list[_Pair] = []
    repaired = 0
    line: list[_Pair] = []

    def flush() -> None:
        nonlocal repaired
        text = "".join(char for char, _ in line).strip()
        if text and _SPACED_CAPS.match(text):
            out.extend((char, source) for char, source in line if char != " ")
            repaired += 1
        else:
            out.extend(line)
        line.clear()

    for pair in pairs:
        if pair[0] == "\n":
            flush()
            out.append(pair)
        else:
            line.append(pair)
    flush()

    return out, repaired


def normalize(text: str) -> NormalizedText:
    """Clean extracted text without losing the link back to its source."""
    if not text:
        return NormalizedText(text="", offsets=OffsetMap([], 0), original="")

    pairs = _initial_pairs(text)
    pairs = _apply_unicode(pairs)
    pairs = _canonicalise_bullets(pairs)
    pairs = _join_hyphenated(pairs)
    pairs = _collapse_whitespace(pairs)
    pairs, repaired = _repair_spaced_caps(pairs)

    return NormalizedText(
        text="".join(char for char, _ in pairs),
        offsets=OffsetMap(sources=[source for _, source in pairs], original_length=len(text)),
        original=text,
        repaired_spaced_lines=repaired,
    )


def find_all(haystack: str, needle: str) -> list[tuple[int, int]]:
    """Every occurrence of a string, as ranges. Used to locate evidence."""
    if not needle:
        return []
    spans: list[tuple[int, int]] = []
    start = haystack.find(needle)
    while start != -1:
        spans.append((start, start + len(needle)))
        start = haystack.find(needle, start + 1)
    return spans


def line_bounds(text: str, index: int) -> tuple[int, int]:
    """The line containing an offset, as a range."""
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return start, len(text) if end == -1 else end


def line_starts(text: str) -> list[int]:
    """Offsets at which each line begins, for fast lookup."""
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def line_number_at(starts: list[int], index: int) -> int:
    return max(0, bisect_right(starts, index) - 1)
