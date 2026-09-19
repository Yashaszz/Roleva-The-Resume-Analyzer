"""The shared daily LLM counter.

`InMemoryUsageStore` forgets everything when the process restarts, which is fine
in development and wrong in production for two reasons: Render's free tier
restarts instances whenever it likes, and the count needs to be shared if there
is ever more than one of them. A forgotten counter means the free tier is
exceeded rather than guarded.

So the count lives in Postgres, incremented by a function so two analyses
starting at the same moment cannot both read the same number and both proceed.

Writes use the service-role key. `llm_usage` has no user column — it is
service-wide accounting, not anybody's data — and RLS with no policy makes the
function the only way in.
"""

from __future__ import annotations

from datetime import date

from roleva.config import Settings, get_settings
from roleva.llm.budget import UsageStore
from roleva.storage.supabase import Supabase, SupabaseError
from roleva.telemetry.logging import get_logger

logger = get_logger(__name__)


class SupabaseUsageStore(UsageStore):
    """Daily request counts, shared across instances and restarts."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._db = Supabase(service_role=True, settings=self.settings)
        #: Last known good value per model, used when the database is briefly
        #: unreachable. Stale is better than zero: zero would reopen the tap.
        self._last_known: dict[tuple[date, str], int] = {}

    async def get(self, day: date, model: str) -> int:
        try:
            rows = await self._db.select(
                "llm_usage",
                columns="request_count",
                filters={"day": f"eq.{day.isoformat()}", "model": f"eq.{model}"},
                limit=1,
            )
        except SupabaseError:
            # Falling back to the last value we saw keeps the budget guard
            # conservative. Returning 0 here would tell the caller it has the
            # whole day's allowance left, which is the one wrong answer.
            logger.warning("usage.read_failed", model=model)
            return self._last_known.get((day, model), 0)

        count = int(rows[0]["request_count"]) if rows else 0
        self._last_known[(day, model)] = count
        return count

    async def increment(self, day: date, model: str, tokens: int = 0) -> int:
        try:
            count = await self._db.rpc(
                "bump_llm_usage",
                {"p_day": day.isoformat(), "p_model": model, "p_tokens": tokens},
            )
        except SupabaseError:
            # The call has already been made to Gemini by the time this runs.
            # Counting it locally keeps the in-process view honest even when
            # the shared counter is unavailable.
            logger.warning("usage.increment_failed", model=model)
            local = self._last_known.get((day, model), 0) + 1
            self._last_known[(day, model)] = local
            return local

        value = int(count) if isinstance(count, int) else 0
        self._last_known[(day, model)] = value
        return value


def build_usage_store(settings: Settings | None = None) -> UsageStore:
    """The counter appropriate to this environment.

    Falls back to in-memory when Supabase is not configured, so the API still
    runs locally — with the limitation stated in the log rather than hidden.
    """
    config = settings or get_settings()
    if config.supabase_url and config.supabase_service_role_key:
        return SupabaseUsageStore(config)

    from roleva.llm.budget import InMemoryUsageStore

    logger.warning("usage.in_memory", reason="supabase not configured")
    return InMemoryUsageStore()
