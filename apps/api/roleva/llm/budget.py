"""Rate and budget guards for the free LLM tier.

On a paid API the binding constraint is tokens. On Gemini's free tier it is
**requests** — a per-minute ceiling and a per-day ceiling. That inverts the
usual optimisation: batching several logical tasks into one larger call is
correct here, and Roleva holds itself to at most six requests per analysis.

Three guards, in order of how they fail:

  * `TokenBucket`    — smooths bursts against the per-minute limit by waiting.
  * `DailyBudget`    — hard stop against the per-day limit; degrades honestly.
  * `AnalysisBudget` — per-request ceiling, so one analysis cannot run away.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date


class BudgetExceededError(Exception):
    """Raised when a guard refuses a call. Callers map this to a user message."""

    def __init__(self, scope: str, detail: str) -> None:
        self.scope = scope
        self.detail = detail
        super().__init__(f"{scope}: {detail}")


class TokenBucket:
    """Classic token bucket over a rolling minute.

    `acquire()` waits rather than failing: a short wait is a far better outcome
    than a failed analysis, and at Roleva's volume the wait is rarely more than
    a few seconds.
    """

    def __init__(
        self,
        rate_per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if rate_per_minute < 1:
            raise ValueError("rate_per_minute must be at least 1")
        self.capacity = float(rate_per_minute)
        self.refill_per_second = rate_per_minute / 60.0
        self._tokens = float(rate_per_minute)
        # The clock is injected rather than read directly so tests can advance
        # time without sleeping through it.
        self._clock = clock
        self._updated = clock()
        self._lock = asyncio.Lock()

    def _replenish(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._updated)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_second)
        self._updated = now

    def wait_time(self) -> float:
        """Seconds until a token is available. Zero when one is ready now."""
        self._replenish()
        if self._tokens >= 1.0:
            return 0.0
        return (1.0 - self._tokens) / self.refill_per_second

    async def acquire(self) -> float:
        """Take one token, waiting if necessary. Returns seconds waited."""
        waited = 0.0
        while True:
            async with self._lock:
                delay = self.wait_time()
                if delay <= 0.0:
                    self._tokens -= 1.0
                    return waited
            await asyncio.sleep(delay)
            waited += delay


class UsageStore(ABC):
    """Where the daily request count lives.

    In-memory in development; backed by the `llm_usage` table in production so
    the count survives a Render restart and is shared across instances.
    """

    @abstractmethod
    async def get(self, day: date, model: str) -> int: ...

    @abstractmethod
    async def increment(self, day: date, model: str, tokens: int = 0) -> int: ...


@dataclass
class InMemoryUsageStore(UsageStore):
    counts: dict[tuple[date, str], int] = field(default_factory=dict)
    tokens: dict[tuple[date, str], int] = field(default_factory=dict)

    async def get(self, day: date, model: str) -> int:
        return self.counts.get((day, model), 0)

    async def increment(self, day: date, model: str, tokens: int = 0) -> int:
        key = (day, model)
        self.counts[key] = self.counts.get(key, 0) + 1
        self.tokens[key] = self.tokens.get(key, 0) + tokens
        return self.counts[key]

    async def total_for(self, day: date) -> int:
        return sum(count for (d, _), count in self.counts.items() if d == day)


class DailyBudget:
    """Guards the per-day request ceiling across all models.

    Above `soft_limit_ratio` the service is still working but close to the edge,
    which the API surfaces so the UI can warn before anything breaks.
    """

    def __init__(
        self,
        store: UsageStore,
        max_requests_per_day: int,
        *,
        soft_limit_ratio: float = 0.85,
    ) -> None:
        self.store = store
        self.max_requests_per_day = max_requests_per_day
        self.soft_limit_ratio = soft_limit_ratio

    async def used_today(self, models: list[str], day: date | None = None) -> int:
        today = day or date.today()
        counts = [await self.store.get(today, model) for model in models]
        return sum(counts)

    async def check(self, models: list[str], day: date | None = None) -> None:
        used = await self.used_today(models, day)
        if used >= self.max_requests_per_day:
            raise BudgetExceededError(
                "daily",
                f"{used}/{self.max_requests_per_day} requests used today",
            )

    async def is_near_limit(self, models: list[str], day: date | None = None) -> bool:
        used = await self.used_today(models, day)
        return used >= self.max_requests_per_day * self.soft_limit_ratio

    async def record(self, model: str, tokens: int = 0, day: date | None = None) -> None:
        await self.store.increment(day or date.today(), model, tokens)


@dataclass
class AnalysisBudget:
    """Per-analysis call ceiling.

    A tripped ceiling means a stage is retrying in a loop or the pipeline has
    grown an extra call. Failing loudly here keeps a single analysis from
    eating the day's quota.
    """

    max_calls: int
    used: int = 0

    def consume(self, label: str) -> None:
        if self.used >= self.max_calls:
            raise BudgetExceededError(
                "analysis",
                f"{self.max_calls}-call limit reached before '{label}'",
            )
        self.used += 1

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self.used)
