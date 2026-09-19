"""Choosing which bullets to rewrite — deterministically, before any model runs.

The model never decides what needs fixing. It is handed a short list and asked
to rewrite exactly those lines, for three reasons:

1. **Cost.** Sending forty bullets to be assessed burns the free tier on lines
   that were already fine.
2. **Consistency.** "Which of these is weakest?" is a judgement call a model
   answers differently on different runs. Counting missing numbers is not.
3. **Explainability.** Every selected bullet arrives with the specific reasons
   it was selected, so the UI can say *why* a line was singled out instead of
   asserting that it is weak.

The rules here are the same ones the quality metrics already measure. Nothing
new is invented: a bullet is weak because of the things the score already
counted, which keeps the advice and the score telling one story.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from roleva.models.resume import Bullet, ResumeDocument, SkillOrigin
from roleva.quality.metrics import (
    IDEAL_BULLET_WORDS,
    has_number,
    opens_with_action_verb,
    weak_phrases_in,
)

#: At most this many bullets are rewritten. A user given fifteen rewrites edits
#: none of them; the cap is a usability decision, not a cost one.
MAX_SELECTED = 5

#: Below this, a bullet is not worth the user's attention or a model call.
MIN_WEAKNESS = 2.0


@dataclass(frozen=True)
class Weakness:
    key: str
    #: How much this contributes to the selection ranking.
    weight: float
    reason: str


@dataclass
class WeakBullet:
    bullet_id: str
    text: str
    origin: SkillOrigin
    weaknesses: list[Weakness] = field(default_factory=list)
    #: Position in the document, used only to break ties reproducibly.
    order: int = 0

    @property
    def score(self) -> float:
        return round(sum(weakness.weight for weakness in self.weaknesses), 2)

    @property
    def reasons(self) -> list[str]:
        return [weakness.reason for weakness in self.weaknesses]


def _weaknesses(text: str) -> list[Weakness]:
    """Every countable problem with one bullet.

    Weights express how much each problem costs a reader, which is not the same
    as how much it costs the score. A bullet with no outcome is the single most
    common reason a resume reads as a list of duties, so it dominates.
    """
    found: list[Weakness] = []
    words = text.split()

    phrases = weak_phrases_in(text)
    if phrases:
        found.append(
            Weakness(
                key="weak_phrase",
                weight=1.5,
                reason=f'Opens with filler: "{phrases[0]}".',
            )
        )

    if not has_number(text):
        found.append(
            Weakness(
                key="no_outcome",
                weight=1.5,
                reason="No measurable result — nothing tells the reader what changed.",
            )
        )

    if not opens_with_action_verb(text):
        found.append(
            Weakness(
                key="no_action_verb",
                weight=1.0,
                reason="Does not open with an action verb.",
            )
        )

    low, high = IDEAL_BULLET_WORDS
    if len(words) < low:
        found.append(
            Weakness(
                key="too_short",
                weight=1.0,
                reason=f"Only {len(words)} words — too short to show anything.",
            )
        )
    elif len(words) > high:
        found.append(
            Weakness(
                key="too_long",
                weight=0.75,
                reason=f"{len(words)} words — the point is buried.",
            )
        )

    return found


def select_weak_bullets(document: ResumeDocument, *, limit: int = MAX_SELECTED) -> list[WeakBullet]:
    """The bullets worth rewriting, worst first.

    Deterministic: the same document always produces the same list in the same
    order. Ties break on document position, never on iteration order.
    """
    candidates: list[WeakBullet] = []

    for index, (origin, bullet) in enumerate(document.all_bullets()):
        text = bullet.text.strip()
        if not text:
            continue
        weaknesses = _weaknesses(text)
        candidate = WeakBullet(
            bullet_id=bullet.id,
            text=text,
            origin=origin,
            weaknesses=weaknesses,
            order=index,
        )
        if candidate.score >= MIN_WEAKNESS:
            candidates.append(candidate)

    candidates.sort(key=lambda candidate: (-candidate.score, candidate.order))
    return candidates[:limit]


def describe_for_prompt(selected: list[WeakBullet]) -> str:
    """Render the selection as the numbered list the model is asked to rewrite.

    Ids are not sent. The model returns answers by index, and the index is
    mapped back here, so a hallucinated id cannot attach a rewrite to a bullet
    the user never had.
    """
    lines: list[str] = []
    for position, candidate in enumerate(selected, start=1):
        lines.append(f"{position}. {candidate.text}")
        lines.append(f"   problems: {'; '.join(candidate.reasons)}")
    return "\n".join(lines)


def bullet_by_id(document: ResumeDocument, bullet_id: str) -> Bullet | None:
    return next(
        (bullet for _, bullet in document.all_bullets() if bullet.id == bullet_id),
        None,
    )
