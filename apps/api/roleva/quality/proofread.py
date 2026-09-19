"""Basic proofreading flags — doubled words, known misspellings, punctuation slips.

This is deliberately **not** a spell checker. A dictionary-based checker on a
resume is mostly a false-positive generator: it does not know `Zentara`,
`PyTorch`, `Kubernetes`, `Raghavendra` or any of the several hundred proper
nouns a real resume contains, and a tool that flags a candidate's own surname as
a spelling mistake has destroyed its own credibility in one line.

So every check here is **closed-set and high-precision**. A misspelling is only
reported if it appears in a curated list of words that are wrong in every
context. A capitalisation fix is only offered for technologies whose official
spelling is unambiguous. There is no heuristic that can fire on a word this
module has never seen — which is what makes the constraint "must never flag a
correctly-spelled technology name" a property of the design rather than a hope.

**These flags do not affect the score.** The user asked for basic grammar
*flagging*, and a false positive that quietly costs points is far worse than one
that can be read and ignored. Spelling also sits outside the published rubric,
and adding an unpublished term to a score Roleva claims is fully explainable
would be a contradiction.

British spellings are correct. `optimise`, `analyse`, `programme` and
`behaviour` are never flagged; the misspelling list contains no word whose
"error" is merely a different standard.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum

from roleva.models.common import Span
from roleva.models.resume import Bullet, ResumeDocument, SkillOrigin

#: No more than this many flags reach the user. Twenty punctuation notes read as
#: nagging and bury the two that matter.
MAX_FLAGS = 12


class FlagKind(StrEnum):
    MISSPELLING = "misspelling"
    DOUBLED_WORD = "doubled_word"
    SPACE_BEFORE_PUNCTUATION = "space_before_punctuation"
    MISSING_SPACE = "missing_space_after_punctuation"
    REPEATED_PUNCTUATION = "repeated_punctuation"
    TECHNOLOGY_CASING = "technology_casing"
    UNBALANCED_BRACKETS = "unbalanced_brackets"
    LOWERCASE_START = "lowercase_start"
    INCONSISTENT_TERMINATORS = "inconsistent_terminators"


class FlagSeverity(StrEnum):
    #: Wrong by any standard. Fixing it is not a matter of taste.
    ERROR = "error"
    #: Correct but inconsistent or unpolished.
    POLISH = "polish"


#: Words that are wrong in every context. Curated by hand: each entry is a
#: misspelling with no valid reading in British or American English, and no
#: meaning as a proper noun, product or command.
MISSPELLINGS: dict[str, str] = {
    "acheive": "achieve",
    "acheived": "achieved",
    "accomodate": "accommodate",
    "accomodated": "accommodated",
    "adn": "and",
    "buisness": "business",
    "calender": "calendar",
    "catagory": "category",
    "collaberated": "collaborated",
    "colaborated": "collaborated",
    "comminication": "communication",
    "communiction": "communication",
    "definately": "definitely",
    "developement": "development",
    "enviroment": "environment",
    "enviroments": "environments",
    "experiance": "experience",
    "goverment": "government",
    "immediatly": "immediately",
    "independant": "independent",
    "intergrated": "integrated",
    "knowlege": "knowledge",
    "langauge": "language",
    "langauges": "languages",
    "liason": "liaison",
    "maintainance": "maintenance",
    "maintainence": "maintenance",
    "managment": "management",
    "mangement": "management",
    "neccessary": "necessary",
    "necesary": "necessary",
    "nessesary": "necessary",
    "occassion": "occasion",
    "occassionally": "occasionally",
    "occured": "occurred",
    "occuring": "occurring",
    "oppurtunity": "opportunity",
    "particpated": "participated",
    "perfomance": "performance",
    "performace": "performance",
    "personel": "personnel",
    "priviledge": "privilege",
    "proffesional": "professional",
    "profesional": "professional",
    "refered": "referred",
    "relevent": "relevant",
    "responsibilites": "responsibilities",
    "responsibilty": "responsibility",
    "responsiblity": "responsibility",
    "recieve": "receive",
    "recieved": "received",
    "seperate": "separate",
    "seperated": "separated",
    "seperately": "separately",
    "sucess": "success",
    "sucessful": "successful",
    "sucessfully": "successfully",
    "succesful": "successful",
    "succesfully": "successfully",
    "teh": "the",
    "tommorow": "tomorrow",
    "truely": "truly",
    "untill": "until",
    "usefull": "useful",
    "wich": "which",
    "writting": "writing",
    # Technology names misspelled rather than miscased. Kept separate from the
    # casing map because these are errors, not inconsistencies.
    "pyhton": "Python",
    "phyton": "Python",
    "javscript": "JavaScript",
    "javasript": "JavaScript",
    "kubernets": "Kubernetes",
    "kubernates": "Kubernetes",
    "postgress": "PostgreSQL",
}

#: Technologies whose official spelling is unambiguous. Matched
#: case-insensitively and reported only when the written form differs.
#:
#: Deliberately absent, and why:
#:   rest, excel, rust, swift, bootstrap, angular, react (as a verb), go
#:           — all ordinary English words. "Excel at communication" must not be
#:             corrected to "Excel at communication".
#:   git     — lowercase is correct at a command line.
#:   pandas  — officially lowercase; "Pandas" is not an error.
#:   nginx   — officially lowercase.
#:   npm     — officially lowercase.
#: A term belongs here only when its lowercase form has no other valid reading.
TECHNOLOGY_CASING: tuple[str, ...] = (
    "JavaScript",
    "TypeScript",
    "Node.js",
    "Next.js",
    "GitHub",
    "GitLab",
    "MySQL",
    "PostgreSQL",
    "SQLite",
    "MongoDB",
    "Kubernetes",
    "Kafka",
    "Redis",
    "Python",
    "Java",
    "Django",
    "Flask",
    "FastAPI",
    "TensorFlow",
    "PyTorch",
    "NumPy",
    "Jupyter",
    "Linux",
    "Ubuntu",
    "macOS",
    "iOS",
    "Android",
    "GraphQL",
    "Tailwind",
    "Figma",
    "Jenkins",
    "Terraform",
    "Ansible",
    "Selenium",
    "Firebase",
    "Supabase",
    "Vue",
    "Svelte",
    "Kotlin",
    "Scala",
    "MATLAB",
    "Tableau",
    "PowerPoint",
)

_CASING_LOOKUP = {name.lower(): name for name in TECHNOLOGY_CASING}

#: Words that legitimately repeat in English. Without these, "had had" and
#: "that that" are reported as errors.
_LEGITIMATE_REPEATS = frozenset({"had", "that", "no", "very", "so"})

_WORD = re.compile(r"[A-Za-z][A-Za-z.']*")
_DOUBLED = re.compile(r"\b([A-Za-z]{2,})(\s+)(\1)\b", re.IGNORECASE)
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([,;:.!?])")
_REPEATED_PUNCT = re.compile(r"([!?,;:])\1+|(?<!\.)\.{2}(?!\.)")

#: A comma or semicolon immediately followed by a letter. Digits are excluded so
#: "40,000" survives, and a following capital after a full stop is excluded so
#: abbreviations and decimals are not reported.
_MISSING_SPACE = re.compile(r"([,;])(?=[A-Za-z])")

#: Characters that mean the surrounding token is a URL, path, email or version
#: number rather than prose. Casing checks skip anything adjacent to one.
_TOKEN_NEIGHBOURS = "/@:\\_-"

#: Bullet glyphs stripped before the first word is inspected. The same set
#: the deterministic metrics strip, kept identical so the two modules agree
#: on where a bullet's text begins.
_BULLET_MARKERS = "•-–— "


@dataclass
class WritingFlag:
    """One proofreading observation, pointing at the text that caused it."""

    kind: FlagKind
    severity: FlagSeverity
    #: The exact text at fault, as written.
    found: str
    message: str
    fix: str
    #: The bullet it was found in, for display context.
    context: str = ""
    bullet_id: str | None = None
    #: Character offsets within `context`.
    local_start: int = 0
    local_end: int = 0
    #: Absolute location in the source document, when the bullet's own span is
    #: reliable enough to offset from. Absent is normal, not an error.
    span: Span | None = None
    #: How many times this same issue appears across the document.
    occurrences: int = 1

    @property
    def key(self) -> tuple[str, str]:
        """Identity for deduplication: the same typo twice is one finding."""
        return (self.kind.value, self.found.lower())


@dataclass
class ProofreadReport:
    flags: list[WritingFlag] = field(default_factory=list)
    #: Flags found before the display cap was applied.
    total_found: int = 0

    @property
    def errors(self) -> list[WritingFlag]:
        return [flag for flag in self.flags if flag.severity is FlagSeverity.ERROR]

    @property
    def polish(self) -> list[WritingFlag]:
        return [flag for flag in self.flags if flag.severity is FlagSeverity.POLISH]


def _span_for(bullet: Bullet, start: int, end: int, found: str) -> Span | None:
    """Translate an offset inside a bullet into a document span.

    Only produced when the bullet's recorded span quotes the bullet text
    verbatim. If the structurer cleaned the text after recording the span, the
    offsets no longer line up, and a span that points at the wrong characters is
    worse than no span at all — `Span.verify` would drop it downstream anyway.
    """
    span = bullet.span
    if span is None or span.text != bullet.text:
        return None
    return Span(
        doc=span.doc,
        start=span.start + start,
        end=span.start + end,
        text=found,
        page=span.page,
        section_id=span.section_id,
    )


def _flags_in(text: str, bullet: Bullet) -> list[WritingFlag]:
    found: list[WritingFlag] = []

    def add(
        kind: FlagKind,
        severity: FlagSeverity,
        start: int,
        end: int,
        message: str,
        fix: str,
    ) -> None:
        quoted = text[start:end]
        found.append(
            WritingFlag(
                kind=kind,
                severity=severity,
                found=quoted,
                message=message,
                fix=fix,
                context=text,
                bullet_id=bullet.id,
                local_start=start,
                local_end=end,
                span=_span_for(bullet, start, end, quoted),
            )
        )

    for match in _WORD.finditer(text):
        word = match.group()
        stripped = word.strip(".'")
        lowered = stripped.lower()

        correct = MISSPELLINGS.get(lowered)
        if correct is not None:
            # Preserve the writer's capitalisation when suggesting the fix.
            suggestion = correct.capitalize() if stripped[:1].isupper() else correct
            add(
                FlagKind.MISSPELLING,
                FlagSeverity.ERROR,
                match.start(),
                match.start() + len(stripped),
                f'"{stripped}" is misspelled.',
                f'Use "{suggestion}".',
            )
            continue

        official = _CASING_LOOKUP.get(lowered)
        if official is not None and stripped != official:
            before = text[match.start() - 1] if match.start() else ""
            after = text[match.end()] if match.end() < len(text) else ""
            if before in _TOKEN_NEIGHBOURS or after in _TOKEN_NEIGHBOURS or after.isdigit():
                continue  # part of a URL, path, identifier or "python3"
            add(
                FlagKind.TECHNOLOGY_CASING,
                FlagSeverity.POLISH,
                match.start(),
                match.start() + len(stripped),
                f'"{stripped}" is conventionally written "{official}".',
                f'Write it as "{official}". Recruiters read exact tool names quickly.',
            )

    for match in _DOUBLED.finditer(text):
        if match.group(1).lower() in _LEGITIMATE_REPEATS:
            continue
        add(
            FlagKind.DOUBLED_WORD,
            FlagSeverity.ERROR,
            match.start(),
            match.end(),
            f'"{match.group(1)}" is repeated.',
            f'Delete the second "{match.group(3)}".',
        )

    for match in _SPACE_BEFORE_PUNCT.finditer(text):
        add(
            FlagKind.SPACE_BEFORE_PUNCTUATION,
            FlagSeverity.ERROR,
            match.start(),
            match.end(),
            f"There is a space before the {match.group(1)!r}.",
            "Remove the space before the punctuation mark.",
        )

    for match in _MISSING_SPACE.finditer(text):
        add(
            FlagKind.MISSING_SPACE,
            FlagSeverity.ERROR,
            match.start(),
            match.end() + 1,
            f"Missing a space after the {match.group(1)!r}.",
            "Add a space after the punctuation mark.",
        )

    for match in _REPEATED_PUNCT.finditer(text):
        add(
            FlagKind.REPEATED_PUNCTUATION,
            FlagSeverity.POLISH,
            match.start(),
            match.end(),
            "Punctuation is repeated.",
            "Use a single punctuation mark.",
        )

    if text.count("(") != text.count(")"):
        add(
            FlagKind.UNBALANCED_BRACKETS,
            FlagSeverity.ERROR,
            0,
            min(len(text), 40),
            "The brackets in this line do not close.",
            "Add the missing bracket.",
        )

    first = _WORD.search(text.lstrip(_BULLET_MARKERS))
    if first is not None:
        word = first.group()
        # An all-lowercase technology name is handled by the casing check; only
        # ordinary words are reported here.
        if word[0].islower() and word.lower() not in _CASING_LOOKUP:
            offset = text.index(word)
            add(
                FlagKind.LOWERCASE_START,
                FlagSeverity.POLISH,
                offset,
                offset + len(word),
                "This line starts with a lowercase letter.",
                "Capitalise the first word, as the other bullets do.",
            )

    return found


def _terminator_flag(texts: list[str]) -> WritingFlag | None:
    """Report mixed use of full stops at the ends of bullets.

    Either convention is fine. Mixing them within one document is the thing a
    reader notices, so the flag describes the inconsistency and names the
    majority style rather than asserting a house rule.
    """
    if len(texts) < 4:
        return None

    with_stop = [text for text in texts if text.rstrip().endswith(".")]
    count = len(with_stop)
    if count in (0, len(texts)):
        return None

    minority = min(count, len(texts) - count)
    if minority / len(texts) > 0.35:
        return None  # genuinely mixed content, not a slip

    majority_has_stop = count > len(texts) / 2
    style = "end with a full stop" if majority_has_stop else "omit the full stop"
    return WritingFlag(
        kind=FlagKind.INCONSISTENT_TERMINATORS,
        severity=FlagSeverity.POLISH,
        found=f"{minority} of {len(texts)} bullets",
        message=f"Most of your bullets {style}, but {minority} do not.",
        fix="Pick one and apply it to every bullet.",
        occurrences=minority,
    )


def _dedupe(flags: list[WritingFlag]) -> list[WritingFlag]:
    """Collapse repeats, keeping the first occurrence and counting the rest."""
    counts = Counter(flag.key for flag in flags)
    seen: set[tuple[str, str]] = set()
    unique: list[WritingFlag] = []
    for flag in flags:
        if flag.key in seen:
            continue
        seen.add(flag.key)
        flag.occurrences = counts[flag.key]
        unique.append(flag)
    return unique


def proofread(document: ResumeDocument) -> ProofreadReport:
    """Find basic writing errors across every bullet in the document.

    Deterministic: no model, no network, no wordlist beyond the two curated maps
    in this module. The same resume always produces the same flags.
    """
    bullets: list[tuple[SkillOrigin, Bullet]] = [
        (origin, bullet) for origin, bullet in document.all_bullets() if bullet.text.strip()
    ]

    raw: list[WritingFlag] = []
    for _, bullet in bullets:
        raw.extend(_flags_in(bullet.text, bullet))

    flags = _dedupe(raw)

    # The summary is prose and conventionally ends in a full stop, so counting
    # it would report an inconsistency in every resume that has one.
    terminator = _terminator_flag(
        [bullet.text for origin, bullet in bullets if origin is not SkillOrigin.SUMMARY]
    )
    if terminator is not None:
        flags.append(terminator)

    # Errors before polish, so the cap keeps what is unambiguously wrong.
    flags.sort(key=lambda flag: (flag.severity is not FlagSeverity.ERROR, -flag.occurrences))

    return ProofreadReport(flags=flags[:MAX_FLAGS], total_found=len(flags))
