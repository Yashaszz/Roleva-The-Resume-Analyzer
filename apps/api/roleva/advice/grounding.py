"""The grounding validator — the thing that stops Roleva inventing your career.

A model asked to improve *"Worked on the payment system"* will happily return
*"Rebuilt the payment system, cutting transaction failures by 35% across 2M
monthly users."* It reads beautifully. It is also a fabrication the user might
paste into a resume and be asked about in an interview.

So a rewrite is checked before it is ever shown: **every fact in the suggestion
must already exist in the original.** Facts are the three things a model
invents and an interviewer checks —

  * **numbers** — 35%, 2M, three years
  * **technologies** — Kubernetes, Django, PostgreSQL
  * **proper nouns** — employers, products, clients

A suggestion introducing any of them is rejected. It is regenerated once with
the violation named, and if it comes back ungrounded again it is dropped and the
user simply sees one fewer suggestion. Dropping is always the safe failure:
nobody is harmed by missing advice, and someone can be harmed by fabricated
advice they trusted.

Two deliberate strictnesses:

1. **Derived numbers are rejected.** "820ms to 210ms" does not license "a 74%
   reduction", even though the arithmetic is right. Percentages a model computes
   are a common source of subtly wrong claims, and the user can always add it
   themselves knowing what it means.
2. **The original bullet is the source of truth**, not the whole resume. Facts
   from elsewhere would let a rewrite pull a number out of a different job.
   Context that genuinely belongs to the bullet — its role title and employer —
   is passed in explicitly by the caller.

Rephrasing is unrestricted. The model may restructure, strengthen the verb, cut
filler and reorder freely: none of that invents anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from roleva.matching import taxonomy

#: Words that start a sentence or are simply conventional capitals, and so are
#: not evidence of a proper noun.
_COMMON_CAPITALS = frozenset(
    """
    a an the and or but if when while for to of in on at by with from as into
    built created developed designed led managed improved reduced increased
    implemented delivered launched shipped wrote automated migrated optimised
    optimized refactored tested deployed maintained analysed analyzed built
    collaborated coordinated mentored owned drove partnered presented
    i my we our their this that these those there here it its
    monday tuesday wednesday thursday friday saturday sunday
    january february march april may june july august september october
    november december
    """.split()
)

#: Digits with optional separators, decimals, magnitude suffix or percent sign.
_NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([kKmMbB])?(%)?")

_CAPITALISED = re.compile(r"\b([A-Z][a-zA-Z]{2,})\b")
_SENTENCE_START = re.compile(r"(?:^|[.!?]\s+)$")

_MAGNITUDE = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


class FactKind(StrEnum):
    NUMBER = "number"
    TECHNOLOGY = "technology"
    PROPER_NOUN = "proper_noun"


@dataclass(frozen=True)
class Fact:
    kind: FactKind
    #: Normalised form, used for comparison.
    value: str
    #: What actually appeared in the text, for the error message.
    surface: str

    def __str__(self) -> str:
        return self.surface


@dataclass
class GroundingResult:
    grounded: bool
    violations: list[Fact] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """A sentence naming what was invented, used to correct the model."""
        if self.grounded:
            return "grounded"
        return ", ".join(f"{fact.kind.value} '{fact.surface}'" for fact in self.violations[:4])


def _numbers(text: str) -> set[Fact]:
    """Numeric facts, normalised so formatting changes are not new facts.

    "40,000", "40000" and "40K" are the same claim written three ways, and a
    validator that treats them as different would reject correct rewrites.
    """
    out: set[Fact] = set()
    for match in _NUMBER.finditer(text):
        digits, suffix, percent = match.groups()
        try:
            value = float(digits.replace(",", ""))
        except ValueError:  # pragma: no cover - the regex guarantees digits
            continue
        if suffix:
            value *= _MAGNITUDE[suffix.lower()]
        normalised = f"{value:g}"
        if percent:
            normalised += "%"
        out.add(Fact(kind=FactKind.NUMBER, value=normalised, surface=match.group().strip()))
    return out


def _technologies(text: str) -> tuple[set[Fact], set[str]]:
    """Skills the taxonomy recognises, by canonical name.

    Canonical rather than literal, so "Postgres" in the original covers
    "PostgreSQL" in the rewrite. Expanding an abbreviation is not a new claim.

    The words those matches consumed come back too, because a recognised
    technology must not also be counted as a proper noun: "PostgreSQL" is one
    fact, and double-counting it would reject the very expansion the canonical
    form exists to allow.

    Positions from the taxonomy index the *normalised* text, not the original,
    so they are used only to read words back out of that same normalised
    string — never to slice the text that was passed in.
    """
    haystack = taxonomy.normalise(text)
    facts: set[Fact] = set()
    consumed: set[str] = set()

    for canonical, start, end in taxonomy.find_in_text(text):
        facts.add(Fact(kind=FactKind.TECHNOLOGY, value=canonical, surface=canonical))
        consumed.update(haystack[start:end].lower().split())
        consumed.update(canonical.lower().replace(".", " ").split())

    return facts, consumed


def _proper_nouns(text: str, consumed: set[str] | None = None) -> set[Fact]:
    """Capitalised words that are not sentence openers or ordinary words.

    Deliberately imprecise in the safe direction: an over-detected proper noun
    can only cause a rewrite to be regenerated, while an under-detected one
    would let an invented employer through.
    """
    out: set[Fact] = set()
    covered = consumed or set()

    for match in _CAPITALISED.finditer(text):
        word = match.group(1)
        lowered = word.lower()
        if lowered in _COMMON_CAPITALS or lowered in covered:
            continue
        if _SENTENCE_START.search(text[: match.start()]):
            continue  # capitalised only because it opens a sentence
        out.add(Fact(kind=FactKind.PROPER_NOUN, value=lowered, surface=word))
    return out


def extract_facts(text: str) -> set[Fact]:
    """Every checkable claim in a piece of text."""
    technologies, consumed = _technologies(text)
    return _numbers(text) | technologies | _proper_nouns(text, consumed)


def _keys(facts: set[Fact]) -> set[tuple[str, str]]:
    return {(fact.kind.value, fact.value) for fact in facts}


def check(
    *,
    original: str,
    suggestion: str,
    context: str = "",
) -> GroundingResult:
    """Whether `suggestion` introduces any fact absent from `original`.

    `context` is content that genuinely belongs to this bullet — its job title
    and employer — so a rewrite may name the company it was already filed under
    without that counting as an invention.
    """
    permitted = _keys(extract_facts(original) | extract_facts(context))
    claimed = extract_facts(suggestion)

    violations = sorted(
        (fact for fact in claimed if (fact.kind.value, fact.value) not in permitted),
        key=lambda fact: (fact.kind.value, fact.value),
    )
    return GroundingResult(grounded=not violations, violations=violations)


def check_prose(*, text: str, allowed_numbers: set[float]) -> GroundingResult:
    """Looser check for generated prose about the analysis rather than a rewrite.

    Prose may name any technology or employer already in the documents, but it
    may not state a number the engine did not compute. This is what keeps a
    generated sentence from quietly rounding a score or inventing a percentile.
    """
    permitted = {f"{value:g}" for value in allowed_numbers}
    permitted |= {f"{value:g}%" for value in allowed_numbers}

    violations = sorted(
        (fact for fact in _numbers(text) if fact.value not in permitted),
        key=lambda fact: fact.value,
    )
    return GroundingResult(grounded=not violations, violations=violations)
