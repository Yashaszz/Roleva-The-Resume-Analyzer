"""Priority cues and quantifiers — the deterministic layer over extraction.

Priority weighting drives the Job Match score, so it is never left to a model
alone. A model asked to judge importance will drift run to run, and a score
that moves without the inputs moving is exactly what Roleva promises not to do.

Instead the model proposes a priority and these rules override it. The signals
are the ones postings actually use: the wording around a requirement, the
heading it sits under, whether it appears in the job title, and how often it is
repeated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from roleva.models.job import Priority, Quantifier

#: Wordings that make a requirement mandatory.
_MUST_CUES = (
    "required",
    "require",
    "must have",
    "must be",
    "must possess",
    "essential",
    "mandatory",
    "minimum",
    "at minimum",
    "you must",
    "candidates must",
    "necessary",
    "non-negotiable",
    "critical",
)

#: Wordings that make a requirement optional, however strongly phrased.
_NICE_CUES = (
    "preferred",
    "nice to have",
    "nice-to-have",
    "a plus",
    "plus if",
    "bonus",
    "desirable",
    "desired",
    "ideally",
    "would be great",
    "advantageous",
    "beneficial",
    "good to have",
    "we would love",
    "not required",
    "not necessary",
    "no ",
    "optional",
)

#: Wordings between the two. "Strongly preferred" is more than nice, less than
#: required, and collapsing the three tiers into two loses real information.
_STRONG_CUES = (
    "strongly preferred",
    "highly preferred",
    "strongly desired",
    "should have",
    "expected",
    "looking for",
    "we expect",
    "important",
)

#: Headings that set the priority for everything beneath them.
_HEADING_PRIORITY: tuple[tuple[tuple[str, ...], Priority], ...] = (
    (
        ("strongly preferred", "highly desirable"),
        Priority.STRONG,
    ),
    (
        (
            "required",
            "requirements",
            "minimum requirements",
            "must have",
            "essential",
            "essential criteria",
            "what you need",
            "qualifications",
            "minimum qualifications",
            "key requirements",
            "required qualifications",
            "required skills",
        ),
        Priority.MUST,
    ),
    (
        (
            "preferred",
            "preferred qualifications",
            "nice to have",
            "nice-to-have",
            "desirable",
            "desired",
            "bonus",
            "a plus",
            "good to have",
            "pluses",
            "extras",
            "optional",
        ),
        Priority.NICE,
    ),
)

#: "3+ years", "at least 2 years", "minimum of 5 years".
_YEARS = re.compile(
    r"(\d+(?:\.\d+)?)\s*\+?\s*(?:-\s*\d+\s*)?(?:or\s+more\s+)?year",
    re.IGNORECASE,
)
_YEARS_WORDS = {
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
}
_YEARS_WORD_RE = re.compile(r"\b(" + "|".join(_YEARS_WORDS) + r")\s*\+?\s*year", re.IGNORECASE)

#: A statement that a requirement does NOT apply. These invert priority rather
#: than raising it, and missing them turns "a PhD is not required" into a
#: mandatory doctorate.
_NEGATIONS = (
    "not required",
    "not a requirement",
    "is not necessary",
    "no need",
    "not expected",
    "do not need",
    "don't need",
    "not looking for",
    "without",
    "no prior",
    "no formal",
)


@dataclass(frozen=True)
class CueResult:
    priority: Priority
    #: True when a rule fired, as opposed to falling back to the model's guess.
    from_rule: bool
    reason: str


def find_quantifier(text: str) -> Quantifier | None:
    """Extract a years-of-experience requirement, in digits or words."""
    match = _YEARS.search(text)
    if match:
        return Quantifier(years=float(match.group(1)), raw=match.group(0).strip())

    match = _YEARS_WORD_RE.search(text)
    if match:
        return Quantifier(years=_YEARS_WORDS[match.group(1).lower()], raw=match.group(0).strip())

    return None


def is_negated(text: str) -> bool:
    """Whether the text says a requirement does not apply."""
    lowered = text.lower()
    return any(phrase in lowered for phrase in _NEGATIONS)


def priority_from_heading(heading: str) -> Priority | None:
    """The priority a section heading implies for everything under it.

    The longest matching phrase wins rather than the first tier checked.
    "Preferred qualifications" contains "qualifications", which is a must-have
    cue, and reading it that way turns every optional item into a requirement.
    """
    cleaned = re.sub(r"[^a-z\s]", " ", heading.lower()).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return None

    best: tuple[int, Priority] | None = None
    for phrases, priority in _HEADING_PRIORITY:
        for phrase in phrases:
            matches = cleaned == phrase or phrase in cleaned
            if matches and (best is None or len(phrase) > best[0]):
                best = (len(phrase), priority)

    return best[1] if best else None


def priority_from_text(text: str) -> Priority | None:
    """The priority a requirement's own wording implies.

    Checked strongest-first: "strongly preferred" contains "preferred", and
    reading it as merely nice-to-have would lose the distinction the posting
    was drawing.
    """
    lowered = text.lower()

    if any(cue in lowered for cue in _STRONG_CUES):
        return Priority.STRONG
    if any(cue in lowered for cue in _NICE_CUES):
        return Priority.NICE
    if any(cue in lowered for cue in _MUST_CUES):
        return Priority.MUST
    return None


def resolve_priority(
    *,
    proposed: Priority,
    text: str,
    heading: str | None = None,
    in_job_title: bool = False,
    mention_count: int = 1,
) -> CueResult:
    """Decide a requirement's priority, overriding the model where a rule fires.

    Precedence, strongest first:

      1. A negation — the posting explicitly says this is not required.
      2. Appearing in the job title — a "Python Developer" needs Python.
      3. The requirement's own wording.
      4. The heading it sits under.
      5. Repetition, which escalates by one tier.
      6. The model's proposal.
    """
    if is_negated(text):
        return CueResult(Priority.NICE, True, "explicitly stated as not required")

    if in_job_title:
        return CueResult(Priority.MUST, True, "named in the job title")

    from_text = priority_from_text(text)
    if from_text is not None:
        return CueResult(from_text, True, "wording of the requirement")

    from_heading = priority_from_heading(heading) if heading else None
    if from_heading is not None:
        return CueResult(from_heading, True, f"listed under '{heading}'")

    if mention_count >= 3:
        escalated = _escalate(proposed)
        if escalated is not proposed:
            return CueResult(escalated, True, f"repeated {mention_count} times")

    return CueResult(proposed, False, "as extracted")


def _escalate(priority: Priority) -> Priority:
    if priority is Priority.NICE:
        return Priority.STRONG
    if priority is Priority.STRONG:
        return Priority.MUST
    return priority
