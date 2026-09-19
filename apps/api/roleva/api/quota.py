"""Rate limiting and the daily capacity guard.

Two different protections that are easy to confuse:

* **Per-user and per-IP limits** stop one person consuming what is meant for
  everyone. Five analyses per user per day, twenty per IP per hour.
* **The global daily budget** stops Roleva as a whole from exceeding Gemini's
  free tier. When it trips, nobody gets an analysis until tomorrow.

They need different messages, because they are different situations from the
user's side. "You have used your five for today" is their own doing and resets
predictably. "Roleva has reached today's capacity" is not their fault, and
saying "you are rate limited" there would be both confusing and untrue.

The counter is incremented by a Postgres function rather than read-then-written
here. Two browser tabs submitting at the same moment is an ordinary thing for a
user to do, and losing that race means a free-tier quota gets spent twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from roleva.api.errors import ErrorCode, RolevaError
from roleva.config import Settings, get_settings
from roleva.storage.supabase import Supabase, SupabaseError
from roleva.telemetry.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class LimitWindow:
    """One counter: what it keys on and how long it lasts."""

    key: str
    window_start: datetime
    limit: int
    code: ErrorCode


def day_window(now: datetime | None = None) -> datetime:
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def hour_window(now: datetime | None = None) -> datetime:
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return moment.replace(minute=0, second=0, microsecond=0)


def windows_for(
    *,
    user_id: str,
    client_ip: str | None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> list[LimitWindow]:
    """The limits one request must pass.

    The per-user limit is checked first, so a user who has genuinely used their
    five analyses is told that, rather than being told their network is busy.
    """
    config = settings or get_settings()
    checks = [
        LimitWindow(
            key=f"user:{user_id}",
            window_start=day_window(now),
            limit=config.user_daily_analysis_quota,
            code=ErrorCode.QUOTA_EXCEEDED,
        )
    ]
    if client_ip:
        checks.append(
            LimitWindow(
                key=f"ip:{client_ip}",
                window_start=hour_window(now),
                limit=config.ip_hourly_analysis_quota,
                code=ErrorCode.RATE_LIMITED,
            )
        )
    return checks


async def consume(
    db: Supabase,
    windows: list[LimitWindow],
    *,
    fail_open: bool = True,
) -> None:
    """Increment each counter and raise if any limit is exceeded.

    `fail_open` decides what happens when the limiter itself is broken. It
    defaults to true: a database hiccup should not stop people using the
    product, and the global daily budget is the real protection against the
    free tier being exhausted. The event is logged loudly so a limiter that has
    been failing open for a week is visible rather than silent.
    """
    for window in windows:
        try:
            count = await db.rpc(
                "bump_rate_limit",
                {"p_key": window.key, "p_window_start": window.window_start.isoformat()},
            )
        except SupabaseError:
            logger.error("ratelimit.unavailable", key=window.key, fail_open=fail_open)
            if fail_open:
                continue
            raise RolevaError(ErrorCode.CAPACITY_REACHED) from None

        if isinstance(count, int) and count > window.limit:
            logger.info("ratelimit.exceeded", key=window.key, count=count, limit=window.limit)
            raise RolevaError(window.code)


async def check_daily_capacity(db: Supabase, settings: Settings | None = None) -> None:
    """Refuse when Roleva as a whole has used the day's model requests.

    Deliberately a separate error from the per-user quota. This is not the
    user's fault and no action of theirs will clear it, so the message says the
    service is at capacity rather than implying they did something.
    """
    config = settings or get_settings()
    today = day_window().date().isoformat()

    try:
        rows = await db.select(
            "llm_usage",
            columns="request_count",
            filters={"day": f"eq.{today}"},
        )
    except SupabaseError:
        # The budget guard in the LLM client is the second line of defence and
        # does not depend on this table, so failing open here is safe.
        logger.warning("capacity.check_failed")
        return

    used = sum(int(row.get("request_count") or 0) for row in rows)
    if used >= config.llm_max_rpd:
        logger.warning("capacity.reached", used=used, limit=config.llm_max_rpd)
        raise RolevaError(ErrorCode.CAPACITY_REACHED)
