"""The anonymous score sample write path.

Roleva promises real percentiles rather than invented ones, and a percentile
needs a cohort. This module writes the only rows that make one possible.

**The table has no `user_id`, and that is a schema-level decision, not a
convention this module happens to follow.** There is no column to write a user
into, so no future change here can quietly start linking samples to people.

Three further things are given up on purpose, because a row that cannot be
traced needs more than a missing id:

1. **Time is truncated to the hour.** `created_at` defaults to `now()` in the
   schema, and a microsecond-precision timestamp is a join key: anyone holding
   both tables could match a sample to the analysis that produced it. An
   explicit hour-truncated value overrides the default, which collapses that
   join into a bucket shared by everyone who ran an analysis that hour.
2. **Scores are rounded to whole points.** A distribution does not need decimals,
   and `73.4 / 61.8 / 88.1` is close to a fingerprint.
3. **Nothing else travels.** No analysis id, no resume hash, no job title, no
   region. Only the cohort key and four numbers.

A failed write never fails an analysis. The user's report does not depend on
this row existing, so the error is logged and swallowed — degrading the cohort
is acceptable, losing someone's report to a statistics side effect is not.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from roleva.config import Settings, get_settings
from roleva.models.scoring import ScoreReport

logger = logging.getLogger(__name__)

#: Samples below this confidence are not recorded. A cohort assembled from
#: uncertain parses and missing rubric judgements is a cohort of noise, and
#: percentiles drawn from it would be precise about nothing. The scoring engine
#: already lowers confidence when a stage degraded, so this one gate covers a
#: failed rubric call and a poor parse alike.
MIN_CONFIDENCE = 0.9

TIMEOUT = 10.0


@dataclass(frozen=True)
class ScoreSample:
    """One anonymous row. Every field here is either a cohort key or a score."""

    role_family: str
    seniority: str
    overall: float
    job_match: float
    ats: float
    quality: float
    must_coverage: float
    created_at: datetime

    def to_payload(self) -> dict[str, Any]:
        return {
            "role_family": self.role_family,
            "seniority": self.seniority,
            "overall": self.overall,
            "job_match": self.job_match,
            "ats": self.ats,
            "quality": self.quality,
            "must_coverage": self.must_coverage,
            "created_at": self.created_at.isoformat(),
        }


def _truncate_to_hour(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def sample_from(
    scores: ScoreReport,
    *,
    role_family: str,
    seniority: str,
    now: Callable[[], datetime] | None = None,
) -> ScoreSample:
    """Build a sample from a score report. Pure, given a clock.

    The clock is a parameter so tests can pin the timestamp — the same reason
    the scoring engine takes no clock at all.
    """
    clock = now or (lambda: datetime.now(UTC))
    return ScoreSample(
        role_family=role_family,
        seniority=seniority,
        overall=round(scores.overall.value),
        job_match=round(scores.job_match.value),
        ats=round(scores.ats.value),
        quality=round(scores.quality.value),
        must_coverage=round(scores.must_coverage, 2),
        created_at=_truncate_to_hour(clock()),
    )


def refusal_reason(scores: ScoreReport) -> str | None:
    """Why this report must not be sampled, or None if it may be.

    Returning the reason rather than a boolean means the decision shows up in
    logs, so an empty cohort can be explained instead of investigated.
    """
    confidence = min(
        scores.overall.confidence,
        scores.job_match.confidence,
        scores.quality.confidence,
        scores.ats.confidence,
    )
    if confidence < MIN_CONFIDENCE:
        return f"confidence {confidence:.2f} below {MIN_CONFIDENCE}"
    if not scores.overall.value:
        return "no overall score"
    return None


class SampleWriter(Protocol):
    """Where samples go. A protocol so the orchestrator never imports httpx."""

    async def write(self, sample: ScoreSample) -> bool: ...


class NullSampleWriter:
    """Records nothing. Used in tests and whenever Supabase is unconfigured.

    Roleva has to run end to end with no database configured — that is how the
    parser and scorer are developed — so "no writer" is a supported state rather
    than a failure.
    """

    def __init__(self) -> None:
        self.written: list[ScoreSample] = []

    async def write(self, sample: ScoreSample) -> bool:
        self.written.append(sample)
        return False


class SupabaseSampleWriter:
    """Writes to `public.score_samples` over the REST API.

    Uses the service-role key, which is correct here and only here: the table has
    RLS enabled and **no policy**, so it is unreachable with the anon key by
    design. There is no user whose token could be used instead — that is the
    entire point of the table.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def configured(self) -> bool:
        return bool(self._settings.supabase_url and self._settings.supabase_service_role_key)

    @property
    def _endpoint(self) -> str:
        return f"{self._settings.supabase_url.rstrip('/')}/rest/v1/score_samples"

    @property
    def _headers(self) -> dict[str, str]:
        key = self._settings.supabase_service_role_key
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # Nothing is read back. The row has no id worth keeping, and asking
            # for one would hand this process a handle to a row it should not be
            # able to find again.
            "Prefer": "return=minimal",
        }

    async def write(self, sample: ScoreSample) -> bool:
        if not self.configured:
            logger.debug("sample.skipped", extra={"reason": "supabase not configured"})
            return False

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                self._endpoint, headers=self._headers, json=sample.to_payload()
            )
        if response.status_code >= 400:
            logger.warning(
                "sample.rejected",
                extra={"status": response.status_code, "body": response.text[:200]},
            )
            return False
        return True


async def record(
    scores: ScoreReport,
    *,
    role_family: str,
    seniority: str,
    writer: SampleWriter | None = None,
    now: Callable[[], datetime] | None = None,
) -> bool:
    """Record one anonymous sample. Never raises.

    Called once per completed analysis, after the report has been returned to the
    user. Returns whether a row was written, for telemetry — not for control
    flow, because nothing upstream should behave differently either way.
    """
    reason = refusal_reason(scores)
    if reason is not None:
        logger.info("sample.refused", extra={"reason": reason})
        return False

    sample = sample_from(scores, role_family=role_family, seniority=seniority, now=now)
    target = writer or SupabaseSampleWriter()

    try:
        return await target.write(sample)
    except Exception:
        # A statistics side effect must never surface to the user, and must never
        # be retried into a loop that burns the free tier.
        logger.warning("sample.write_failed", exc_info=True)
        return False
