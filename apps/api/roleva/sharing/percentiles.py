"""Cohort percentiles, and the rule that they usually do not appear.

Roleva promises real percentiles rather than invented ones. The consequence is
that for most of the product's life there are none: a role family needs thirty
samples before a percentile means anything, and a new product has none at all.

So this reads `cohort_stats`, which the database only populates for cohorts
above the floor. There is no code path here that can produce a percentile from
a thin cohort, because there is no row to read. The floor lives in SQL rather
than in an `if` statement for exactly that reason — a UI bug cannot render what
was never sent.

When no cohort exists the report falls back to the curated expected bands,
which are always labelled "typical range" and never as a percentile.
"""

from __future__ import annotations

from roleva.models.scoring import Percentile, ScoreKind, ScoreReport
from roleva.storage.supabase import Supabase, SupabaseError
from roleva.telemetry.logging import get_logger

logger = get_logger(__name__)

#: Mirrors the HAVING clause in `refresh_cohort_stats`. Duplicated so the
#: constant is visible to a reader here, and asserted against the migration by
#: the tests so the two cannot drift.
MINIMUM_SAMPLE = 30

_METRICS: dict[str, ScoreKind] = {
    "overall": ScoreKind.OVERALL,
    "job_match": ScoreKind.JOB_MATCH,
    "quality": ScoreKind.QUALITY,
    "ats": ScoreKind.ATS,
}


def _position(value: float, row: dict[str, float]) -> float:
    """Where a score sits in the cohort, from the five stored quantiles.

    Interpolated between the bracketing quantiles rather than snapped to one:
    reporting "you are at the 75th" for everything between p50 and p75 would be
    a coarser claim than the data supports.
    """
    points = [
        (0.0, "p10", 10.0),
        (10.0, "p25", 25.0),
        (25.0, "p50", 50.0),
        (50.0, "p75", 75.0),
        (75.0, "p90", 90.0),
    ]

    previous_pct = 0.0
    previous_value = float(row["p10"])

    if value <= previous_value:
        # Below the tenth percentile. Reported as 10 rather than extrapolating
        # into a tail the five stored quantiles say nothing about.
        return 10.0

    for _, key, pct in points:
        current = float(row[key])
        if value <= current:
            span = current - previous_value
            if span <= 0:
                return pct
            share = (value - previous_value) / span
            return round(previous_pct + share * (pct - previous_pct), 1)
        previous_pct = pct
        previous_value = current

    return 90.0


async def attach(
    scores: ScoreReport,
    *,
    db: Supabase,
    role_family: str,
    seniority: str,
) -> ScoreReport:
    """Fill in percentiles where a cohort is large enough to have them.

    Returns the report unchanged when there is no cohort, which is the common
    case and not an error.
    """
    try:
        rows = await db.select(
            "cohort_stats",
            columns="metric,p10,p25,p50,p75,p90,sample_size",
            filters={
                "role_family": f"eq.{role_family}",
                "seniority": f"eq.{seniority}",
            },
        )
    except SupabaseError:
        logger.info("percentiles.unavailable")
        return scores

    if not rows:
        return scores

    values = scores.as_dict()
    found: list[Percentile] = []

    for row in rows:
        kind = _METRICS.get(str(row["metric"]))
        if kind is None:
            continue

        sample_size = int(row["sample_size"])
        if sample_size < MINIMUM_SAMPLE:
            # Belt and braces. The SQL should never emit such a row, and if it
            # somehow does, it stops here rather than reaching a user.
            logger.warning("percentiles.thin_cohort", sample_size=sample_size)
            continue

        score = values.get(kind.value)
        if score is None:
            continue

        found.append(
            Percentile(
                kind=kind,
                percentile=_position(score.value, row),
                sample_size=sample_size,
                role_family=role_family,
                seniority=seniority,
            )
        )

    scores.percentiles = found
    return scores
