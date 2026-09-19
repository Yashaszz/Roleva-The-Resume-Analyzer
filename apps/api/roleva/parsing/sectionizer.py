"""Section detection.

Resumes label their sections inconsistently — "Experience", "Work History",
"Where I've Worked", "Professional Background" — and some creative templates use
no recognisable words at all. Matching a fixed list of headings therefore fails
on exactly the resumes that most need help.

So headings are *scored* from several independent signals rather than matched.
A line that is short, bold, larger than the body text, preceded by a gap and
followed by bullets is a heading whatever it says. The word list is the
strongest single signal, not the only one, which is what lets "Things I've
Built" be recognised as a projects section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from roleva.models.resume import SectionKind
from roleva.parsing.normalizer import NormalizedText, line_bounds
from roleva.parsing.pdf_reader import ExtractedDocument, Line

#: Known heading wordings, by the section they indicate. Matching is on
#: normalised lowercase text, so casing and punctuation do not matter.
HEADING_LEXICON: dict[SectionKind, tuple[str, ...]] = {
    SectionKind.SUMMARY: (
        "summary",
        "professional summary",
        "career summary",
        "profile",
        "professional profile",
        "about",
        "about me",
        "objective",
        "career objective",
        "overview",
        "introduction",
        "who i am",
    ),
    SectionKind.EXPERIENCE: (
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
        "work history",
        "career history",
        "positions",
        "professional background",
        "relevant experience",
        "industry experience",
        "internships",
        "internship experience",
        "where i worked",
        "where ive worked",
        "work",
    ),
    SectionKind.EDUCATION: (
        "education",
        "academic background",
        "academics",
        "qualifications",
        "academic qualifications",
        "educational background",
        "schooling",
        "degrees",
        "education and training",
    ),
    SectionKind.SKILLS: (
        "skills",
        "technical skills",
        "core skills",
        "key skills",
        "competencies",
        "core competencies",
        "technologies",
        "tech stack",
        "toolkit",
        "my toolkit",
        "tools",
        "expertise",
        "areas of expertise",
        "proficiencies",
        "technical proficiencies",
        "skills and tools",
    ),
    SectionKind.PROJECTS: (
        "projects",
        "personal projects",
        "side projects",
        "key projects",
        "selected projects",
        "academic projects",
        "portfolio",
        "things i built",
        "things ive built",
        "what i built",
        "work samples",
    ),
    SectionKind.CERTIFICATIONS: (
        "certifications",
        "certificates",
        "licenses",
        "licences",
        "professional certifications",
        "credentials",
        "courses",
        "relevant coursework",
        "coursework",
        "training",
    ),
    SectionKind.AWARDS: (
        "awards",
        "honors",
        "honours",
        "achievements",
        "accomplishments",
        "awards and honors",
        "recognition",
        "scholarships",
    ),
    SectionKind.PUBLICATIONS: (
        "publications",
        "papers",
        "research",
        "research experience",
        "conference papers",
        "patents",
    ),
    SectionKind.VOLUNTEER: (
        "volunteer",
        "volunteering",
        "volunteer experience",
        "community",
        "community involvement",
        "extracurricular",
        "extracurricular activities",
        "activities",
        "leadership",
        "positions of responsibility",
    ),
    SectionKind.LANGUAGES: ("languages", "language proficiency", "languages known"),
    SectionKind.INTERESTS: ("interests", "hobbies", "hobbies and interests", "personal interests"),
    SectionKind.CONTACT: ("contact", "contact details", "contact information", "details"),
}

#: Reverse lookup, longest phrases first so "work experience" beats "work".
_LEXICON: tuple[tuple[str, SectionKind], ...] = tuple(
    sorted(
        ((phrase, kind) for kind, phrases in HEADING_LEXICON.items() for phrase in phrases),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
)

_APOSTROPHE = re.compile(r"['’‘]")
_PUNCT = re.compile(r"[^a-z0-9\s]+")
_SENTENCE_END = re.compile(r"[.!?,;:]$")

#: A line scoring at least this is treated as a heading.
HEADING_THRESHOLD = 3.0

#: Headings are short. Anything longer is a sentence.
_MAX_HEADING_WORDS = 6
_MAX_HEADING_CHARS = 45


@dataclass
class HeadingSignals:
    """Why a line was, or was not, judged a heading. Kept for explainability
    and for debugging a resume that parsed oddly."""

    lexicon: bool = False
    larger_font: bool = False
    bold: bool = False
    all_caps: bool = False
    short: bool = False
    no_terminal_punctuation: bool = False
    preceded_by_gap: bool = False
    followed_by_content: bool = False

    @property
    def score(self) -> float:
        return (
            2.5 * self.lexicon
            + 2.0 * self.larger_font
            + 1.0 * self.bold
            + 1.0 * self.all_caps
            + 0.75 * self.short
            + 0.5 * self.no_terminal_punctuation
            + 0.75 * self.preceded_by_gap
            + 0.5 * self.followed_by_content
        )

    @property
    def is_heading(self) -> bool:
        return self.score >= HEADING_THRESHOLD


@dataclass
class Section:
    kind: SectionKind
    heading: str | None
    start: int
    end: int
    confidence: float
    order: int
    signals: HeadingSignals | None = None

    def text(self, document: str) -> str:
        return document[self.start : self.end]


@dataclass
class SectionReport:
    sections: list[Section] = field(default_factory=list)
    #: Lines that scored as headings but matched no known wording.
    unrecognised_headings: list[str] = field(default_factory=list)

    def of_kind(self, kind: SectionKind) -> Section | None:
        return next((s for s in self.sections if s.kind is kind), None)

    @property
    def kinds(self) -> set[SectionKind]:
        return {section.kind for section in self.sections}


def classify_heading(text: str) -> tuple[SectionKind | None, bool]:
    """Match heading text against the lexicon.

    Returns the section kind and whether the match was exact. A heading that
    merely *contains* a known word ("Technical Skills & Tools") is a weaker
    signal than one that is exactly it.
    """
    cleaned = _PUNCT.sub(" ", _APOSTROPHE.sub("", text.lower())).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return None, False

    for phrase, kind in _LEXICON:
        if cleaned == phrase:
            return kind, True

    # Only consider a partial match on something heading-shaped. Otherwise
    # any line mentioning "technologies" or "experience" in passing becomes
    # a section, which is how a job title ends up as a heading.
    if len(cleaned.split()) <= 4:
        for phrase, kind in _LEXICON:
            if len(phrase) >= 5 and re.search(rf"\b{re.escape(phrase)}\b", cleaned):
                return kind, False

    return None, False


def _line_for_offset(lines: list[Line], original_offset: int) -> Line | None:
    for line in lines:
        if line.start <= original_offset < line.end:
            return line
    return None


def score_line(
    text: str,
    *,
    source: Line | None,
    body_size: float,
    gap_before: bool,
    content_after: bool,
) -> HeadingSignals:
    stripped = text.strip()
    if not stripped:
        return HeadingSignals()

    # "Languages: Python, JavaScript" is a labelled list inside a section, not a
    # section of its own. A colon with substantial content after it is the
    # giveaway, and without this veto every such line opens a spurious section.
    label, separator, remainder = stripped.partition(":")
    if separator and len(remainder.strip()) > 3 and len(label.split()) <= 3:
        return HeadingSignals()

    kind, _ = classify_heading(stripped)
    words = stripped.split()
    letters = [char for char in stripped if char.isalpha()]

    return HeadingSignals(
        lexicon=kind is not None,
        larger_font=bool(source and body_size and source.max_size > body_size * 1.08),
        bold=bool(source and source.is_bold),
        all_caps=bool(letters) and all(char.isupper() for char in letters),
        short=len(words) <= _MAX_HEADING_WORDS and len(stripped) <= _MAX_HEADING_CHARS,
        no_terminal_punctuation=not _SENTENCE_END.search(stripped),
        preceded_by_gap=gap_before,
        followed_by_content=content_after,
    )


def sectionize(
    normalized: NormalizedText,
    extracted: ExtractedDocument,
) -> SectionReport:
    """Split a resume into sections, with a confidence for each."""
    text = normalized.text
    if not text.strip():
        return SectionReport()

    raw_lines = text.split("\n")
    body_size = extracted.body_size

    # Offsets of each line in the normalised text.
    offsets: list[int] = []
    cursor = 0
    for line in raw_lines:
        offsets.append(cursor)
        cursor += len(line) + 1

    headings: list[tuple[int, int, str, SectionKind | None, HeadingSignals]] = []

    for index, line_text in enumerate(raw_lines):
        stripped = line_text.strip()
        if not stripped:
            continue

        original_start, _ = normalized.original_span(offsets[index], offsets[index] + 1)
        source = _line_for_offset(extracted.lines, original_start)

        gap_before = index > 0 and not raw_lines[index - 1].strip()
        content_after = any(later.strip() for later in raw_lines[index + 1 : index + 3])

        signals = score_line(
            stripped,
            source=source,
            body_size=body_size,
            gap_before=gap_before,
            content_after=content_after,
        )
        if signals.is_heading:
            kind, _ = classify_heading(stripped)
            headings.append((offsets[index], index, stripped, kind, signals))

    report = SectionReport()

    # A resume's name is usually the largest, boldest line on the page, so it
    # scores as a heading on appearance alone. Anything above the first heading
    # whose *wording* identifies a section is top matter, not a section of its
    # own — otherwise the name becomes a heading and the contact block vanishes.
    first_classified = next(
        (position for position, heading in enumerate(headings) if heading[3] is not None),
        None,
    )
    if first_classified is not None:
        headings = headings[first_classified:]
    elif headings:
        # No recognised wording anywhere. Keep the strongest-scoring candidates
        # rather than treating the whole document as one block.
        headings = [h for h in headings if h[4].score >= HEADING_THRESHOLD + 1.0]

    # Everything before the first heading is the contact block: on almost every
    # resume the name and details sit at the top with no label above them.
    if not headings or headings[0][0] > 0:
        first_boundary = headings[0][0] if headings else len(text)
        if text[:first_boundary].strip():
            report.sections.append(
                Section(
                    kind=SectionKind.CONTACT,
                    heading=None,
                    start=0,
                    end=first_boundary,
                    confidence=0.9 if headings else 0.5,
                    order=0,
                )
            )

    for position, (start, _, heading_text, kind, signals) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(text)
        body_start = min(line_bounds(text, start)[1] + 1, end)

        if kind is None:
            report.unrecognised_headings.append(heading_text)

        # A heading recognised by wording is trusted more than one recognised
        # only by how it looks.
        confidence = min(1.0, signals.score / 6.0) if kind else min(0.6, signals.score / 8.0)

        report.sections.append(
            Section(
                kind=kind or SectionKind.OTHER,
                heading=heading_text,
                start=body_start,
                end=end,
                confidence=round(confidence, 2),
                order=len(report.sections),
                signals=signals,
            )
        )

    return report
