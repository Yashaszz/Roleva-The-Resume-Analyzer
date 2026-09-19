"""Deterministic writing metrics.

These measure the things about resume writing that can actually be counted:
how many bullets carry a number, how many open with a real verb, how many are
padded with "responsible for". They make up roughly sixty per cent of the
quality score, and because they are counted rather than judged, that portion of
the score never moves between runs.

Each metric returns a value, a target, and the specific bullets that failed —
so a low score can point at the lines that caused it rather than delivering a
verdict the user has to take on trust.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from roleva.models.resume import Bullet, ResumeDocument, SkillOrigin

#: Verbs that describe doing something, as opposed to having been present.
#: Only the opening word of a bullet is checked against this.
ACTION_VERBS = frozenset(
    """
    achieved adapted added administered advanced analysed analyzed
    answered applied architected assembled assessed audited authored
    automated balanced built calculated centralised centralized clarified
    coached collaborated compiled completed composed computed conducted
    configured consolidated constructed consulted converted coordinated
    created cut debugged decreased defined delivered demonstrated deployed
    designed detected determined developed devised diagnosed directed
    documented doubled drafted drove earned edited eliminated enabled
    engineered enhanced established evaluated executed expanded expedited
    explained extended facilitated finalised finalized forecast formed
    formulated founded generated guided handled headed identified
    implemented improved increased influenced initiated innovated
    inspected installed instituted integrated interpreted introduced
    invented investigated launched led leveraged maintained managed mapped
    marketed measured mentored merged migrated minimised minimized modeled
    modelled modernised modernized monitored negotiated operated optimised
    optimized orchestrated organised organized overhauled oversaw
    performed pioneered planned prepared presented prioritised prioritized
    processed produced programmed proposed prototyped published queried
    raised rationalised rationalized rebuilt received recommended
    reconciled recorded recovered redesigned reduced refactored refined
    reorganised reorganized repaired replaced reported researched resolved
    restored restructured revamped reviewed revised scaled scheduled
    secured selected shipped simplified solved sourced spearheaded
    specified standardised standardized streamlined strengthened
    structured studied supervised supported surveyed sustained synthesised
    synthesized tested tracked trained transformed translated troubleshot
    uncovered unified updated upgraded validated verified wrote
    """.split()
)

#: Padding that adds length without adding information.
WEAK_PHRASES = (
    "responsible for",
    "duties included",
    "tasked with",
    "helped with",
    "worked on",
    "assisted with",
    "involved in",
    "participated in",
    "was part of",
    "in charge of",
    "hard working",
    "hard-working",
    "team player",
    "detail oriented",
    "go-getter",
    "think outside the box",
    "results-driven",
    "self-motivated",
    "various tasks",
    "etc.",
)

#: Any run of digits. A count is a count, so "Mentored 3 interns" is as
#: quantified as "40,000 requests per day" — an earlier version required two
#: digits and rejected the first, which is both wrong and discouraging.
#: Bare years are excluded separately.
_DIGITS = re.compile(r"\d[\d,.]*")

#: A year on its own measures nothing about what was achieved.
_BARE_YEAR = re.compile(r"(?:19|20)\d{2}")

_FIRST_PERSON = re.compile(r"\b(?:I|me|my|mine|myself)\b")
_PASSIVE = re.compile(r"\b(?:was|were|been|being|is|are|be)\s+\w+(?:ed|en)\b", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z']+")

#: Bullets outside this band are hard to read: too short says nothing, too long
#: buries the point.
IDEAL_BULLET_WORDS = (8, 30)


@dataclass
class Metric:
    """One measurement, with the evidence behind it."""

    key: str
    label: str
    value: float
    target: float
    #: True when higher is better. Weak-phrase density is the other way round.
    higher_is_better: bool = True
    #: The bullets that caused the score, so a finding can point at them.
    offenders: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def meets_target(self) -> bool:
        return self.value >= self.target if self.higher_is_better else self.value <= self.target

    @property
    def attainment(self) -> float:
        """How close to target, as 0.0-1.0.

        Used by the scoring engine, which needs a comparable number across
        metrics that are measured on different scales.
        """
        if self.higher_is_better:
            return min(1.0, self.value / self.target) if self.target else 1.0
        if self.value <= self.target:
            return 1.0
        # Degrade smoothly rather than falling off a cliff at the threshold.
        excess = self.value - self.target
        return max(0.0, 1.0 - excess / max(self.target, 0.1))


@dataclass
class MetricsReport:
    metrics: list[Metric] = field(default_factory=list)
    bullet_count: int = 0

    def get(self, key: str) -> Metric | None:
        return next((metric for metric in self.metrics if metric.key == key), None)

    @property
    def failing(self) -> list[Metric]:
        return [metric for metric in self.metrics if not metric.meets_target]


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def has_number(text: str) -> bool:
    """Whether a bullet contains something countable.

    Years on their own do not count: "Worked there in 2024" quantifies nothing
    about what was achieved.
    """
    for match in _DIGITS.finditer(text):
        cleaned = match.group().rstrip(".,")
        if _BARE_YEAR.fullmatch(cleaned):
            continue  # a bare year is not an achievement
        return True
    return False


def opens_with_action_verb(text: str) -> bool:
    cleaned = text.strip().lstrip("•-–— ").strip()
    words = _words(cleaned)
    return bool(words) and words[0].lower() in ACTION_VERBS


def weak_phrases_in(text: str) -> list[str]:
    lowered = text.lower()
    return [phrase for phrase in WEAK_PHRASES if phrase in lowered]


def _all_bullets(document: ResumeDocument) -> list[tuple[SkillOrigin, Bullet]]:
    return [(origin, bullet) for origin, bullet in document.all_bullets() if bullet.text.strip()]


def measure(document: ResumeDocument) -> MetricsReport:
    """Measure everything countable about how this resume is written."""
    bullets = _all_bullets(document)
    report = MetricsReport(bullet_count=len(bullets))

    if not bullets:
        return report

    texts = [bullet.text for _, bullet in bullets]
    total = len(texts)

    quantified = [text for text in texts if has_number(text)]
    report.metrics.append(
        Metric(
            key="quantification",
            label="Bullets containing a measurable result",
            value=len(quantified) / total,
            target=0.40,
            offenders=[text for text in texts if not has_number(text)][:5],
            detail=(
                f"{len(quantified)} of {total} bullets include a number. Numbers are "
                "what turn a description of duties into evidence of impact."
            ),
        )
    )

    strong_openers = [text for text in texts if opens_with_action_verb(text)]
    report.metrics.append(
        Metric(
            key="action_verbs",
            label="Bullets opening with an action verb",
            value=len(strong_openers) / total,
            target=0.80,
            offenders=[text for text in texts if not opens_with_action_verb(text)][:5],
            detail=(
                f"{len(strong_openers)} of {total} bullets start with a verb describing "
                "what you did."
            ),
        )
    )

    low, high = IDEAL_BULLET_WORDS
    well_sized = [text for text in texts if low <= len(_words(text)) <= high]
    report.metrics.append(
        Metric(
            key="bullet_length",
            label="Bullets of a readable length",
            value=len(well_sized) / total,
            target=0.75,
            offenders=[text for text in texts if not low <= len(_words(text)) <= high][:5],
            detail=f"A readable bullet runs to between {low} and {high} words.",
        )
    )

    with_weak = [text for text in texts if weak_phrases_in(text)]
    report.metrics.append(
        Metric(
            key="weak_phrases",
            label="Bullets padded with filler",
            value=len(with_weak) / total,
            target=0.0,
            higher_is_better=False,
            offenders=with_weak[:5],
            detail=(
                '"Responsible for" and "worked on" describe presence rather than contribution.'
            ),
        )
    )

    passive = [text for text in texts if _PASSIVE.search(text)]
    report.metrics.append(
        Metric(
            key="passive_voice",
            label="Bullets in the passive voice",
            value=len(passive) / total,
            target=0.10,
            higher_is_better=False,
            offenders=passive[:5],
            detail="The passive voice hides who did the work — which here is you.",
        )
    )

    first_person = [text for text in texts if _FIRST_PERSON.search(text)]
    report.metrics.append(
        Metric(
            key="first_person",
            label="Bullets using I or my",
            value=len(first_person) / total,
            target=0.0,
            higher_is_better=False,
            offenders=first_person[:5],
            detail="Resume bullets conventionally omit the pronoun; the reader knows it is you.",
        )
    )

    openers = [
        _words(text.strip().lstrip("•-–— "))[0].lower()
        for text in texts
        if _words(text.strip().lstrip("•-–— "))
    ]
    repeated = {word for word in openers if openers.count(word) > 2}
    report.metrics.append(
        Metric(
            key="opener_variety",
            label="Variety in how bullets open",
            value=1.0 - (len(repeated) / max(1, len(set(openers)))),
            target=0.80,
            offenders=sorted(repeated)[:5],
            detail=(
                f"{len(repeated)} verb(s) open more than two bullets each."
                if repeated
                else "Bullet openings are varied."
            ),
        )
    )

    return report
