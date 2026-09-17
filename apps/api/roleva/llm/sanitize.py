"""PII redaction at the LLM boundary.

Roleva runs on Gemini's free tier, whose terms let Google use submitted content
to improve their products. A resume is one of the most PII-dense documents an
ordinary person owns. So nothing identifying is ever sent: names, emails,
phones, addresses and personal links are replaced with stable placeholders
before the request, and restored locally afterwards.

What stays in the text is what the analysis actually needs — job titles,
employers, schools, skills, dates, bullet content. Roleva scores *what you did*,
not *who you are*, so redaction costs essentially nothing in quality. It also
means the model cannot see name-based signals, which removes a bias vector.

Offsets shift when placeholders differ in length from the text they replace, so
`RedactionMap` carries a translation table: any offset the model reports against
the redacted text can be mapped back to the original document.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from enum import StrEnum

from roleva.models.resume import ContactInfo


class PiiKind(StrEnum):
    NAME = "name"
    EMAIL = "email"
    PHONE = "phone"
    LOCATION = "location"
    URL = "url"
    DOB = "dob"


#: Lower number wins when two candidate matches overlap. Structured, unambiguous
#: things are matched first so a phone number inside a URL is not split.
_PRIORITY: dict[PiiKind, int] = {
    PiiKind.EMAIL: 0,
    PiiKind.URL: 1,
    PiiKind.DOB: 2,
    PiiKind.PHONE: 3,
    PiiKind.NAME: 4,
    PiiKind.LOCATION: 5,
}

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

_URL_RE = re.compile(
    r"\b(?:https?://|www\.)[^\s<>\"')\]]+"
    r"|\b(?:linkedin\.com|github\.com|gitlab\.com|behance\.net|dribbble\.com)/[^\s<>\"')\]]+",
    re.IGNORECASE,
)

# Deliberately conservative: requires a separator or a leading +/(, so that
# years ("2019 2023") and metrics ("40000 requests") are not mistaken for phones.
_PHONE_RE = re.compile(
    r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?|\d{2,4}[\s.-])\d{2,4}[\s.-]?\d{2,6}(?![\w.])"
)

_DOB_RE = re.compile(
    r"\b(?:D\.?O\.?B\.?|Date\s+of\s+Birth|Birth\s*date)\b\s*[:\-]?\s*[\w/.,-]{4,20}",
    re.IGNORECASE,
)

#: Phrases that look like an attempt to steer the model rather than resume
#: content. These are reported, not obeyed — and because every score is computed
#: in Python, an injection has no number to move even if one slips through.
_INJECTION_RE = re.compile(
    r"(ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions"
    r"|disregard\s+(?:the\s+)?(?:above|previous)"
    r"|you\s+are\s+now\s+"
    r"|system\s*(?:prompt|message)\s*:"
    r"|rate\s+this\s+(?:resume\s+)?\d+\s*(?:/|out\s+of)\s*\d+"
    r"|(?:score|give)\s+(?:this|me)\s+(?:a\s+)?(?:100|10/10|perfect)"
    r"|as\s+an\s+ai\s+(?:language\s+)?model)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PiiMatch:
    kind: PiiKind
    start: int
    end: int
    original: str
    placeholder: str


@dataclass
class RedactionMap:
    """Everything needed to undo a redaction and to translate offsets."""

    matches: list[PiiMatch] = field(default_factory=list)
    #: placeholder -> original value
    values: dict[str, str] = field(default_factory=dict)
    #: Offsets in the redacted text where a shift begins, and the cumulative
    #: delta to add to reach the original offset.
    _breaks: list[int] = field(default_factory=list)
    _deltas: list[int] = field(default_factory=list)

    def restore(self, text: str) -> str:
        """Put the real values back. Longest placeholder first, so `[URL_1]`
        is never damaged by a substring replacement."""
        for placeholder in sorted(self.values, key=len, reverse=True):
            text = text.replace(placeholder, self.values[placeholder])
        return text

    def to_original_offset(self, redacted_offset: int) -> int:
        """Translate an offset in the redacted text back to the original.

        Offsets that land inside a placeholder resolve to the start of the value
        it replaced, which is the behaviour span verification wants.
        """
        if not self._breaks:
            return redacted_offset
        idx = bisect_right(self._breaks, redacted_offset) - 1
        if idx < 0:
            return redacted_offset
        return redacted_offset + self._deltas[idx]

    @property
    def redacted_count(self) -> int:
        return len(self.matches)


def _literal_matches(text: str, value: str, kind: PiiKind) -> list[tuple[PiiKind, int, int, str]]:
    """Every occurrence of a known contact value, matched whole-word."""
    value = value.strip()
    if len(value) < 3:
        return []
    pattern = re.compile(rf"(?<!\w){re.escape(value)}(?!\w)", re.IGNORECASE)
    return [(kind, m.start(), m.end(), m.group()) for m in pattern.finditer(text)]


def _name_part_matches(text: str, full_name: str) -> list[tuple[PiiKind, int, int, str]]:
    """Also catch the name used on its own, e.g. "Priya" in a summary line.

    Parts shorter than four characters are skipped: a name like "Ada" or "Li"
    collides with ordinary words often enough that redacting it would mangle
    the resume's meaning.
    """
    out: list[tuple[PiiKind, int, int, str]] = []
    for part in full_name.split():
        if len(part) >= 4:
            out.extend(_literal_matches(text, part, PiiKind.NAME))
    return out


def redact(text: str, contact: ContactInfo | None = None) -> tuple[str, RedactionMap]:
    """Replace identifying values with placeholders.

    Known values from `contact` are the reliable signal; the regex sweep is a
    safety net for anything the contact block missed (a second email in a
    project line, a phone in a footer).
    """
    candidates: list[tuple[PiiKind, int, int, str]] = []

    for regex, kind in (
        (_EMAIL_RE, PiiKind.EMAIL),
        (_URL_RE, PiiKind.URL),
        (_DOB_RE, PiiKind.DOB),
        (_PHONE_RE, PiiKind.PHONE),
    ):
        candidates.extend((kind, m.start(), m.end(), m.group()) for m in regex.finditer(text))

    if contact is not None:
        if contact.name:
            candidates.extend(_literal_matches(text, contact.name, PiiKind.NAME))
            candidates.extend(_name_part_matches(text, contact.name))
        if contact.email:
            candidates.extend(_literal_matches(text, contact.email, PiiKind.EMAIL))
        if contact.phone:
            candidates.extend(_literal_matches(text, contact.phone, PiiKind.PHONE))
        if contact.location:
            candidates.extend(_literal_matches(text, contact.location, PiiKind.LOCATION))
        for link in contact.links:
            candidates.extend(_literal_matches(text, link, PiiKind.URL))

    # Longest first, then by kind priority, so the most specific match wins a
    # contested region.
    candidates.sort(key=lambda c: (c[1], -(c[2] - c[1]), _PRIORITY[c[0]]))

    accepted: list[tuple[PiiKind, int, int, str]] = []
    last_end = -1
    for kind, start, end, value in candidates:
        if start < last_end:
            continue
        accepted.append((kind, start, end, value))
        last_end = end

    # One placeholder per distinct value, so the same link redacts identically
    # everywhere it appears and restoration is unambiguous.
    assigned: dict[tuple[PiiKind, str], str] = {}
    counters: dict[PiiKind, int] = {}
    rmap = RedactionMap()

    pieces: list[str] = []
    cursor = 0  # position in the original text
    written = 0  # length of redacted text emitted so far
    delta = 0  # original_offset - redacted_offset, after the last break

    for kind, start, end, value in accepted:
        key = (kind, value.lower())
        placeholder = assigned.get(key)
        if placeholder is None:
            counters[kind] = counters.get(kind, 0) + 1
            n = counters[kind]
            placeholder = f"[{kind.value.upper()}]" if n == 1 else f"[{kind.value.upper()}_{n}]"
            assigned[key] = placeholder
            rmap.values[placeholder] = value

        pieces.append(text[cursor:start])
        written += start - cursor
        pieces.append(placeholder)
        written += len(placeholder)

        rmap.matches.append(
            PiiMatch(kind=kind, start=start, end=end, original=value, placeholder=placeholder)
        )

        # The break sits at the END of the placeholder, so offsets falling
        # inside it still use the previous delta and resolve to the start of the
        # value that was replaced.
        delta += len(value) - len(placeholder)
        rmap._breaks.append(written)
        rmap._deltas.append(delta)

        cursor = end

    pieces.append(text[cursor:])
    return "".join(pieces), rmap


def find_injection_markers(text: str) -> list[str]:
    """Phrases that look like prompt injection. Reported to the user as a
    manipulation red flag; never acted on."""
    return sorted({m.group().strip() for m in _INJECTION_RE.finditer(text)})
