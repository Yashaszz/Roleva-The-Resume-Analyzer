"""The verdict paragraph — assembled from computed facts, not written by a model.

This is the first thing a user reads, and it is the easiest place in the product
to accidentally lie. A model handed a report and asked for "a short summary"
will produce something fluent, plausible, and occasionally about a different
resume: a number rounded differently, a skill the user does not have, an
encouraging sentence that contradicts the score above it.

So the paragraph is built by template from values the engine already computed.
Every sentence is conditional on a fact, every number is copied rather than
restated, and there is nothing in it that cannot be traced to the report.

The cost is that it reads as slightly plainer prose than a model would write.
That is an acceptable trade for a verdict that is never wrong, and the parts of
the report where writing quality matters — the bullet rewrites — are where the
model is actually used.

`facts()` also produces the allow-list that the grounded writer checks against,
so the same computed values both build this paragraph and bound what any
generated prose is permitted to claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from roleva.models.evidence import MatchReport, MatchStatus
from roleva.models.job import JobTarget, Priority
from roleva.models.scoring import ScoreReport
from roleva.scoring.engine import load_rubric


@dataclass
class Facts:
    """Every value the verdict is allowed to mention."""

    overall: float
    band_label: str
    band_meaning: str
    must_total: int
    must_matched: int
    matched: int
    partial: int
    missing: int
    ats: float
    quality: float
    job_match: float
    capped: bool
    top_gaps: list[str] = field(default_factory=list)
    listed_not_shown: list[str] = field(default_factory=list)

    def numbers(self) -> set[float]:
        """Numbers the prose may use. The grounding check reads this."""
        return {
            #: The scale maximum. Not a measurement, but "out of 100" has to be
            #: sayable, and it is a published constant rather than a claim.
            100.0,
            self.overall,
            self.ats,
            self.quality,
            self.job_match,
            float(self.must_total),
            float(self.must_matched),
            float(self.matched),
            float(self.partial),
            float(self.missing),
        }


def facts(
    *,
    scores: ScoreReport,
    job: JobTarget,
    matches: MatchReport,
    rubric: dict[str, Any] | None = None,
) -> Facts:
    """Collect the computed values the verdict is built from."""
    config = rubric or load_rubric()
    band = next(
        (entry for entry in config["bands"] if entry["key"] == scores.overall.band.value),
        config["bands"][-1],
    )

    by_id = {match.requirement_id: match for match in matches.matches}
    musts = job.by_priority(Priority.MUST)
    must_matched = sum(
        1 for requirement in musts if (m := by_id.get(requirement.id)) and m.strength >= 0.5
    )

    missing_musts = [
        requirement.text
        for requirement in musts
        if (m := by_id.get(requirement.id)) is None or m.status is MatchStatus.MISSING
    ]

    listed = [
        requirement.text
        for requirement in job.requirements
        if (m := by_id.get(requirement.id))
        and m.status is MatchStatus.PARTIAL
        and 0.0 < m.strength <= 0.5
    ]

    return Facts(
        overall=scores.overall.value,
        band_label=str(band["label"]),
        band_meaning=str(band["meaning"]),
        must_total=len(musts),
        must_matched=must_matched,
        matched=len(matches.by_status(MatchStatus.MATCHED)),
        partial=len(matches.by_status(MatchStatus.PARTIAL)),
        missing=len(matches.by_status(MatchStatus.MISSING)),
        ats=scores.ats.value,
        quality=scores.quality.value,
        job_match=scores.job_match.value,
        capped=scores.overall.cap_applied is not None,
        top_gaps=missing_musts[:3],
        listed_not_shown=listed[:3],
    )


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def headline(data: Facts) -> str:
    """The one sentence the report opens with.

    Separate from `build` because it is set at display size, and a five-sentence
    paragraph at 46px is not a headline — it is a wall. This states the finding;
    the paragraph below it states the consequences.

    Every version is a fact the engine computed. There is no encouraging
    fallback, because a resume that matches nothing should not be greeted with
    an upbeat sentence.
    """
    if data.must_total:
        if data.must_matched == data.must_total:
            return f"You show all {data.must_total} things this job calls essential."
        return (
            f"You show {data.must_matched} of the {data.must_total} things "
            "this job calls essential."
        )

    # A posting with no must-have requirements is unusual but legal: fall back
    # to overall coverage rather than inventing an essential count.
    if data.missing:
        return (
            f"{data.missing} of this role's {data.matched + data.partial + data.missing} "
            "requirements have no evidence in your resume."
        )
    return "Your resume covers everything this posting asks for."


def build(data: Facts) -> str:
    """Compose the verdict from facts. Deterministic and side-effect free."""
    sentences: list[str] = []

    sentences.append(f"{data.band_label} — {data.overall:g} out of 100. {data.band_meaning}")

    if data.must_total:
        sentences.append(
            f"You match {data.must_matched} of {data.must_total} essential "
            f"{_plural(data.must_total, 'requirement')} for this role."
        )
    if data.capped:
        # The cap is the single most important thing on the page when it applies,
        # so it is stated plainly rather than left for the user to infer.
        sentences.append(
            "Your score is capped because of those gaps: matching optional "
            "requirements cannot compensate for missing essential ones."
        )

    if data.top_gaps:
        gaps = ", ".join(data.top_gaps)
        sentences.append(f"The {_plural(len(data.top_gaps), 'gap')} that matters most: {gaps}.")

    if data.listed_not_shown:
        listed = ", ".join(data.listed_not_shown)
        sentences.append(
            f"You list {listed} without showing where you used {_plural(len(data.listed_not_shown), 'it', 'them')} — "
            "a reader cannot tell how far that experience goes."
        )

    if data.ats < 80:
        sentences.append(
            f"Formatting scores {data.ats:g}, which is the cheapest part of this to fix."
        )
    elif data.ats >= 95:
        sentences.append(
            "Your formatting parses cleanly, so nothing is being lost before a human reads it."
        )

    if data.quality < 60:
        sentences.append(
            "The writing is the weakest part: most bullets describe duties rather than results."
        )

    return " ".join(sentences)


def strengths(data: Facts) -> list[str]:
    """Factual positives. Empty is allowed — inventing one would be flattery."""
    out: list[str] = []
    if data.must_total and data.must_matched == data.must_total:
        out.append(
            f"You match every essential requirement ({data.must_total} of {data.must_total})."
        )
    elif data.must_matched:
        out.append(f"You match {data.must_matched} of {data.must_total} essential requirements.")
    if data.ats >= 95:
        out.append("The document parses cleanly in applicant tracking systems.")
    if data.quality >= 75:
        out.append(f"The writing scores {data.quality:g} — bullets are specific and result-led.")
    if data.matched >= 5:
        out.append(
            f"{data.matched} of this role's requirements are demonstrated, not just claimed."
        )
    return out


def weaknesses(data: Facts) -> list[str]:
    out: list[str] = []
    if data.missing:
        out.append(
            f"{data.missing} {_plural(data.missing, 'requirement')} with no evidence at all."
        )
    if data.listed_not_shown:
        out.append(
            f"{len(data.listed_not_shown)} {_plural(len(data.listed_not_shown), 'skill')} "
            "listed but never demonstrated."
        )
    if data.ats < 80:
        out.append(f"Formatting scores {data.ats:g} and may not survive automated parsing.")
    if data.quality < 65:
        out.append(f"Writing scores {data.quality:g}; bullets read as responsibilities.")
    return out
