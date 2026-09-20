"""Tests for the LLM access layer.

A fake provider stands in for Gemini so these run offline, deterministically,
and without spending free-tier quota.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from pydantic import BaseModel, Field

from roleva.config import Settings
from roleva.llm.budget import (
    AnalysisBudget,
    BudgetExceededError,
    DailyBudget,
    InMemoryUsageStore,
    TokenBucket,
)
from roleva.llm.client import (
    LlmClient,
    LlmError,
    SchemaViolationError,
    TransientLlmError,
    _today,
)
from roleva.models.resume import ContactInfo


class Shape(BaseModel):
    name: str
    count: int = Field(ge=0)


class FakeProvider:
    """Replays canned responses and records exactly what it was sent.

    A response may be an exception instance, which is raised instead of
    returned — that is how transient-failure paths are exercised.
    """

    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.embed_calls = 0

    async def generate_json(self, *, prompt: str, model: str, **_: Any) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("FakeProvider ran out of responses")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    async def embed(self, *, texts: list[str], model: str) -> list[list[float]]:
        self.embed_calls += 1
        return [[0.1, 0.2, 0.3] for _ in texts]


def make_client(
    responses: list[str | Exception],
    *,
    transient_retries: int = 2,
) -> tuple[LlmClient, FakeProvider]:
    settings = Settings(llm_max_rpm=600, llm_max_rpd=1000, gemini_api_key="test")
    store = InMemoryUsageStore()
    provider = FakeProvider(responses)
    client = LlmClient(
        provider,
        settings,
        DailyBudget(store, settings.llm_max_rpd),
        transient_retries=transient_retries,
        backoff_base_seconds=0.0,  # no real waiting in tests
    )
    return client, provider


class TestTokenBucket:
    def test_a_fresh_bucket_allows_a_call_immediately(self) -> None:
        assert TokenBucket(10).wait_time() == 0.0

    def test_rejects_a_nonsensical_rate(self) -> None:
        with pytest.raises(ValueError):
            TokenBucket(0)

    async def test_draining_the_bucket_forces_a_wait(self) -> None:
        bucket = TokenBucket(60)  # one token per second
        for _ in range(60):
            await bucket.acquire()
        assert bucket.wait_time() > 0.0

    async def test_tokens_refill_over_time(self) -> None:
        fake_now = 0.0
        bucket = TokenBucket(60, clock=lambda: fake_now)  # one token per second
        for _ in range(60):
            await bucket.acquire()
        assert bucket.wait_time() > 0.0

        fake_now = 10.0  # ten seconds later, ten tokens are back
        assert bucket.wait_time() == 0.0


class TestDailyBudget:
    async def test_allows_calls_below_the_ceiling(self) -> None:
        budget = DailyBudget(InMemoryUsageStore(), max_requests_per_day=3)
        await budget.record("m")
        await budget.check(["m"])

    async def test_refuses_once_the_ceiling_is_reached(self) -> None:
        budget = DailyBudget(InMemoryUsageStore(), max_requests_per_day=2)
        await budget.record("m")
        await budget.record("m")
        with pytest.raises(BudgetExceededError) as exc:
            await budget.check(["m"])
        assert exc.value.scope == "daily"

    async def test_counts_every_model_against_one_shared_ceiling(self) -> None:
        budget = DailyBudget(InMemoryUsageStore(), max_requests_per_day=2)
        await budget.record("flash")
        await budget.record("flash-lite")
        with pytest.raises(BudgetExceededError):
            await budget.check(["flash", "flash-lite"])

    async def test_warns_before_it_refuses(self) -> None:
        budget = DailyBudget(InMemoryUsageStore(), max_requests_per_day=10)
        for _ in range(9):
            await budget.record("m")
        assert await budget.is_near_limit(["m"]) is True
        await budget.check(["m"])  # still allowed

    async def test_yesterdays_usage_does_not_count(self) -> None:
        store = InMemoryUsageStore()
        budget = DailyBudget(store, max_requests_per_day=1)
        await budget.record("m", day=date(2000, 1, 1))
        await budget.check(["m"])


class TestAnalysisBudget:
    def test_allows_calls_up_to_the_limit(self) -> None:
        budget = AnalysisBudget(max_calls=6)
        for i in range(6):
            budget.consume(f"stage-{i}")
        assert budget.remaining == 0

    def test_refuses_the_seventh_call(self) -> None:
        budget = AnalysisBudget(max_calls=6)
        for i in range(6):
            budget.consume(f"stage-{i}")
        with pytest.raises(BudgetExceededError) as exc:
            budget.consume("one-too-many")
        assert "one-too-many" in exc.value.detail


class TestStructuredCalls:
    async def test_valid_output_is_returned_as_a_model(self) -> None:
        client, _ = make_client(['{"name": "django", "count": 3}'])
        result, _ = await client.structured(prompt="hi", output_model=Shape)
        assert result.name == "django"
        assert result.count == 3

    async def test_malformed_output_is_repaired_on_a_second_attempt(self) -> None:
        client, provider = make_client(['{"name": "django"}', '{"name": "django", "count": 1}'])
        result, _ = await client.structured(prompt="hi", output_model=Shape)
        assert result.count == 1
        assert len(provider.prompts) == 2
        assert "did not match the required schema" in provider.prompts[1]

    async def test_two_failures_raise_rather_than_returning_garbage(self) -> None:
        client, _ = make_client(['{"name": 1}', '{"nope": true}'])
        with pytest.raises(SchemaViolationError):
            await client.structured(prompt="hi", output_model=Shape, label="structuring")

    async def test_it_never_retries_more_than_once(self) -> None:
        client, provider = make_client(['{"bad": 1}', '{"bad": 2}'])
        with pytest.raises(SchemaViolationError):
            await client.structured(prompt="hi", output_model=Shape)
        assert len(provider.prompts) == 2


class TestTransientFailures:
    """Free-tier capacity is shared, so 503s are routine rather than a bug."""

    async def test_a_busy_model_is_retried_and_succeeds(self) -> None:
        client, provider = make_client(
            [
                TransientLlmError("busy", status=503),
                '{"name": "django", "count": 2}',
            ]
        )
        result, _ = await client.structured(prompt="hi", output_model=Shape)
        assert result.count == 2
        assert len(provider.prompts) == 2

    async def test_the_retry_budget_applies_per_model(self) -> None:
        """Three attempts on the primary, then three on the fallback, then it
        gives up — rather than hammering one unavailable model six times."""
        client, provider = make_client(
            [TransientLlmError("busy", status=503) for _ in range(6)],
            transient_retries=2,
        )
        with pytest.raises(TransientLlmError):
            await client.structured(prompt="hi", output_model=Shape)
        assert len(provider.prompts) == 6

    async def test_rate_limiting_from_the_vendor_is_retried(self) -> None:
        client, _ = make_client(
            [TransientLlmError("slow down", status=429), '{"name": "a", "count": 0}']
        )
        result, _ = await client.structured(prompt="hi", output_model=Shape)
        assert result.name == "a"

    async def test_a_permanent_error_is_not_retried(self) -> None:
        client, provider = make_client([LlmError("model not found")])
        with pytest.raises(LlmError):
            await client.structured(prompt="hi", output_model=Shape)
        assert len(provider.prompts) == 1

    async def test_a_transient_retry_does_not_consume_the_analysis_budget(self) -> None:
        """A 503 never reached the model, so it is not a logical call."""
        client, _ = make_client(
            [TransientLlmError("busy", status=503), '{"name": "a", "count": 0}']
        )
        budget = AnalysisBudget(max_calls=1)
        await client.structured(prompt="hi", output_model=Shape, analysis_budget=budget)
        assert budget.used == 1


class TestRedactionAtTheBoundary:
    async def test_the_provider_never_receives_identifying_values(self) -> None:
        provider = await _call_with_contact()
        sent = provider.prompts[0]
        assert "Priya Raghavan" not in sent
        assert "priya@example.com" not in sent
        assert "[NAME]" in sent

    async def test_analysis_content_still_reaches_the_provider(self) -> None:
        provider = await _call_with_contact()
        assert "Django" in provider.prompts[0]

    async def test_redaction_can_be_disabled_for_non_resume_text(self) -> None:
        client, provider = make_client(['{"name": "x", "count": 0}'])
        await client.structured(
            prompt="Job description mentioning nobody",
            output_model=Shape,
            redact_pii=False,
        )
        assert provider.prompts[0] == "Job description mentioning nobody"


async def _call_with_contact() -> FakeProvider:
    client, provider = make_client(['{"name": "x", "count": 0}'])
    await client.structured(
        prompt="Priya Raghavan (priya@example.com) built a Django service",
        output_model=Shape,
        contact=ContactInfo(name="Priya Raghavan", email="priya@example.com"),
    )
    return provider


class TestBudgetIntegration:
    async def test_a_call_is_recorded_against_the_daily_budget(self) -> None:
        settings = Settings(llm_max_rpm=600, llm_max_rpd=1, gemini_api_key="test")
        store = InMemoryUsageStore()
        client = LlmClient(
            FakeProvider(['{"name": "a", "count": 1}']),
            settings,
            DailyBudget(store, settings.llm_max_rpd),
        )
        await client.structured(prompt="hi", output_model=Shape)
        assert await store.total_for(date.today()) == 1

    async def test_the_per_analysis_ceiling_stops_a_runaway_pipeline(self) -> None:
        client, _ = make_client(['{"name": "a", "count": 1}'])
        budget = AnalysisBudget(max_calls=1)
        await client.structured(prompt="a", output_model=Shape, analysis_budget=budget)
        with pytest.raises(BudgetExceededError):
            await client.structured(prompt="b", output_model=Shape, analysis_budget=budget)

    async def test_embedding_sends_one_batched_request(self) -> None:
        client, provider = make_client([])
        vectors = await client.embed(["python", "django", "postgres"])
        assert len(vectors) == 3
        assert provider.embed_calls == 1

    async def test_embedding_nothing_costs_nothing(self) -> None:
        client, provider = make_client([])
        assert await client.embed([]) == []
        assert provider.embed_calls == 0


class TestModelFailover:
    """A popular free-tier model can 503 for minutes, long enough that retrying
    the same one is futile. An analysis should survive someone else's traffic
    spike rather than fail on it."""

    async def test_a_persistently_busy_model_fails_over(self) -> None:
        # Three 503s exhaust the primary's retries; the fallback then answers.
        client, provider = make_client(
            [
                TransientLlmError("busy", status=503),
                TransientLlmError("busy", status=503),
                TransientLlmError("busy", status=503),
                '{"name": "ok", "count": 1}',
            ]
        )
        result, _ = await client.structured(prompt="hi", output_model=Shape)
        assert result.name == "ok"
        assert len(provider.prompts) == 4

    async def test_the_model_actually_used_is_recorded(self) -> None:
        """A failover changes which model produced the output, and a report has
        to be able to say so."""
        client, _ = make_client(
            [TransientLlmError("busy", status=503) for _ in range(3)]
            + ['{"name": "ok", "count": 1}']
        )
        await client.structured(prompt="hi", output_model=Shape)
        assert client.last_model_used == client.settings.gemini_model_fallback

    async def test_no_failover_when_the_primary_works(self) -> None:
        client, provider = make_client(['{"name": "ok", "count": 1}'])
        await client.structured(prompt="hi", output_model=Shape)
        assert client.last_model_used == client.settings.gemini_model_main
        assert len(provider.prompts) == 1

    async def test_every_model_failing_raises(self) -> None:
        client, _ = make_client([TransientLlmError("busy", status=503) for _ in range(6)])
        with pytest.raises(TransientLlmError):
            await client.structured(prompt="hi", output_model=Shape)


class TestQuotaExhaustedModels:
    """A live run found this: five calls each paying two retries against a model
    whose daily allowance was gone turned a 20-second analysis into 50."""

    @staticmethod
    def _client(provider: Any, **kwargs: Any) -> LlmClient:
        settings = Settings(
            _env_file=None,
            gemini_api_key="k",
            gemini_model_main="main-model",
            gemini_model_fallback="fallback-model",
        )
        return LlmClient(
            provider,
            settings,
            DailyBudget(InMemoryUsageStore(), settings.llm_max_rpd),
            backoff_base_seconds=0.0,
            **kwargs,
        )

    class _QuotaExhausted:
        """Refuses the main model for quota, answers on the fallback."""

        def __init__(self) -> None:
            self.attempts: list[str] = []

        async def generate_json(self, *, prompt: str, model: str, **_: Any) -> str:
            self.attempts.append(model)
            if model == "main-model":
                raise TransientLlmError("quota exceeded", status=429)
            return '{"value": "ok"}'

        async def embed(self, *, texts: list[str], model: str) -> list[list[float]]:
            return [[0.0] for _ in texts]

    class _Answer(BaseModel):
        value: str

    @pytest.mark.asyncio
    async def test_the_first_call_fails_over_and_succeeds(self) -> None:
        provider = self._QuotaExhausted()
        client = self._client(provider)
        answer, _ = await client.structured(prompt="p", output_model=self._Answer)
        assert answer.value == "ok"
        assert client.last_model_used == "fallback-model"

    @pytest.mark.asyncio
    async def test_the_exhausted_model_is_not_tried_again(self) -> None:
        provider = self._QuotaExhausted()
        client = self._client(provider)

        await client.structured(prompt="p", output_model=self._Answer)
        first_round = list(provider.attempts)
        assert "main-model" in first_round

        provider.attempts.clear()
        await client.structured(prompt="p", output_model=self._Answer)
        assert provider.attempts == ["fallback-model"]

    @pytest.mark.asyncio
    async def test_a_503_does_not_mark_a_model_exhausted(self) -> None:
        """A busy minute is not an empty allowance; the model gets another go."""

        class Busy:
            def __init__(self) -> None:
                self.attempts: list[str] = []

            async def generate_json(self, *, prompt: str, model: str, **_: Any) -> str:
                self.attempts.append(model)
                if model == "main-model":
                    raise TransientLlmError("busy", status=503)
                return '{"value": "ok"}'

            async def embed(self, *, texts: list[str], model: str) -> list[list[float]]:
                return [[0.0] for _ in texts]

        provider = Busy()
        client = self._client(provider)
        await client.structured(prompt="p", output_model=self._Answer)
        provider.attempts.clear()
        await client.structured(prompt="p", output_model=self._Answer)
        assert "main-model" in provider.attempts

    @pytest.mark.asyncio
    async def test_the_last_model_is_never_skipped(self) -> None:
        """An empty candidate list would fail an analysis that could have run."""
        provider = self._QuotaExhausted()
        client = self._client(provider)
        client._exhausted = {"main-model": _today(), "fallback-model": _today()}

        answer, _ = await client.structured(prompt="p", output_model=self._Answer)
        assert answer.value == "ok"

    def test_the_memo_expires_with_the_day(self) -> None:
        from datetime import timedelta

        client = self._client(self._QuotaExhausted())
        client._exhausted = {"main-model": _today() - timedelta(days=1)}
        assert client._is_exhausted("main-model") is False

    @pytest.mark.asyncio
    async def test_a_quota_refusal_is_not_retried(self) -> None:
        """Our own bucket limits requests per minute; a vendor 429 means the
        account is out, and waiting two seconds will not change that."""
        provider = self._QuotaExhausted()
        client = self._client(provider)
        await client.structured(prompt="p", output_model=self._Answer)
        assert provider.attempts.count("main-model") == 1

    @pytest.mark.asyncio
    async def test_a_server_error_is_still_retried(self) -> None:
        class Flaky:
            def __init__(self) -> None:
                self.attempts: list[str] = []

            async def generate_json(self, *, prompt: str, model: str, **_: Any) -> str:
                self.attempts.append(model)
                if len(self.attempts) == 1:
                    raise TransientLlmError("busy", status=503)
                return '{"value": "ok"}'

            async def embed(self, *, texts: list[str], model: str) -> list[list[float]]:
                return [[0.0] for _ in texts]

        provider = Flaky()
        client = self._client(provider)
        answer, _ = await client.structured(prompt="p", output_model=self._Answer)
        assert answer.value == "ok"
        assert len(provider.attempts) == 2
        assert client.last_model_used == "main-model"
