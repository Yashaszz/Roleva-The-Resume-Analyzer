"""LLM access layer.

Everything the pipeline sends to a model goes through `LlmClient`, which owns
the four things that must never be left to a call site:

  1. **Redaction** — no identifying value reaches an external API.
  2. **Schema enforcement** — output is parsed into a Pydantic model, with one
     repair retry that feeds the validation error back, then a hard failure.
     Nothing downstream ever sees a raw completion.
  3. **Budget** — per-minute, per-day and per-analysis guards.
  4. **Accounting** — every call is recorded so cost and quota are observable.

`LlmProvider` is a narrow protocol so Gemini can be swapped for another vendor
by changing configuration rather than code. That matters more than usual here:
the free tier's limits can change under us.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from roleva.config import Settings
from roleva.llm.budget import AnalysisBudget, DailyBudget, TokenBucket
from roleva.llm.sanitize import RedactionMap, redact
from roleva.models.resume import ContactInfo

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LlmError(Exception):
    """A call failed in a way the pipeline must handle, not crash on."""


class SchemaViolationError(LlmError):
    """The model would not produce output matching the schema, twice."""


class TransientLlmError(LlmError):
    """A failure that is worth retrying: rate limiting, or the vendor being busy.

    Free-tier capacity is shared and genuinely flaky — a 503 on a popular model
    is routine, not a bug. Providers normalise their vendor-specific errors into
    this type so the retry policy lives in one place.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        self.status = status
        super().__init__(message)


#: HTTP statuses worth another attempt. 429 is included because the vendor's
#: own limiter can disagree with ours after a restart.
_RETRIABLE_STATUS = {429, 500, 502, 503, 504}


class LlmProvider(Protocol):
    """The seam between Roleva and any specific vendor."""

    async def generate_json(
        self,
        *,
        prompt: str,
        model: str,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        timeout: float = 25.0,
    ) -> str: ...

    async def embed(self, *, texts: list[str], model: str) -> list[list[float]]: ...


class GeminiProvider:
    """Gemini via google-genai.

    Gemini's JSON-schema support is narrower than some vendors': unions and
    deep `$ref` reuse are unreliable. Schemas passed here should stay flat and
    enum-driven. Validation on the way out is what actually guarantees shape.
    """

    def __init__(self, api_key: str) -> None:
        from google import genai  # imported lazily so tests need no key

        self._client = genai.Client(api_key=api_key)

    async def generate_json(
        self,
        *,
        prompt: str,
        model: str,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        timeout: float = 25.0,
    ) -> str:
        from google.genai.types import GenerateContentConfigDict

        config: GenerateContentConfigDict = {
            "temperature": temperature,
            "response_mime_type": "application/json",
        }
        if schema is not None:
            config["response_schema"] = schema

        with _normalised_errors():
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
        text = response.text
        if not text:
            raise LlmError("model returned an empty response")
        return str(text)

    async def embed(self, *, texts: list[str], model: str) -> list[list[float]]:
        # One batched call: on a request-limited tier, embedding each string
        # separately would exhaust the per-minute quota on its own.
        with _normalised_errors():
            response = await self._client.aio.models.embed_content(model=model, contents=texts)
        return [list(e.values or []) for e in (response.embeddings or [])]


@contextmanager
def _normalised_errors() -> Iterator[None]:
    """Translate google-genai's exceptions into Roleva's own error types."""
    from google.genai import errors as genai_errors

    try:
        yield
    except genai_errors.APIError as exc:
        status = getattr(exc, "code", None)
        if status in _RETRIABLE_STATUS:
            raise TransientLlmError(str(exc), status=status) from exc
        raise LlmError(str(exc)) from exc


class LlmClient:
    def __init__(
        self,
        provider: LlmProvider,
        settings: Settings,
        daily_budget: DailyBudget,
        bucket: TokenBucket | None = None,
        transient_retries: int = 2,
        backoff_base_seconds: float = 2.0,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.daily = daily_budget
        self.bucket = bucket or TokenBucket(settings.llm_max_rpm)
        self.transient_retries = transient_retries
        self.backoff_base_seconds = backoff_base_seconds
        #: Which model actually produced the last response. Recorded because
        #: a failover changes it, and a report has to say what generated it.
        self.last_model_used: str = settings.gemini_model_main
        self._models = [
            settings.gemini_model_main,
            settings.gemini_model_light,
            settings.gemini_model_fallback,
            settings.gemini_embed_model,
        ]

    async def structured(
        self,
        *,
        prompt: str,
        output_model: type[T],
        model: str | None = None,
        analysis_budget: AnalysisBudget | None = None,
        label: str = "unnamed",
        contact: ContactInfo | None = None,
        redact_pii: bool = True,
    ) -> tuple[T, RedactionMap]:
        """Run one schema-bound call.

        Returns the validated model plus the redaction map, so the caller can
        restore real values in anything the model quoted back.
        """
        model_name = model or self.settings.gemini_model_main

        if analysis_budget is not None:
            analysis_budget.consume(label)
        await self.daily.check(self._models)

        if redact_pii:
            safe_prompt, rmap = redact(prompt, contact)
        else:
            safe_prompt, rmap = prompt, RedactionMap()

        schema = output_model.model_json_schema()
        attempt_prompt = safe_prompt
        last_error: str | None = None

        # Two attempts: the original, then one repair with the validation error
        # fed back. A model that fails a flat schema twice will not fix itself
        # on a third try, and each retry costs quota.
        for attempt in (1, 2):
            raw = await self._generate_with_retries(
                prompt=attempt_prompt,
                model_name=model_name,
                schema=schema,
                label=label,
            )

            try:
                return output_model.model_validate_json(raw), rmap
            except ValidationError as exc:
                last_error = _summarise(exc)
                logger.warning(
                    "llm.schema_violation",
                    extra={"label": label, "attempt": attempt, "error": last_error},
                )
                if attempt == 2:
                    break
                attempt_prompt = (
                    f"{safe_prompt}\n\n"
                    f"Your previous response did not match the required schema.\n"
                    f"Errors:\n{last_error}\n"
                    f"Return corrected JSON only."
                )

        raise SchemaViolationError(f"{label}: schema not satisfied after 2 attempts — {last_error}")

    async def _generate_with_retries(
        self,
        *,
        prompt: str,
        model_name: str,
        schema: dict[str, Any] | None,
        label: str,
    ) -> str:
        """One logical call, retried and then failed over to another model.

        Free-tier capacity is shared, and a popular model can return 503 for
        minutes at a time — long enough that retrying the same model is futile.
        Rather than fail the whole analysis on someone else's traffic spike,
        each model gets its retry budget and then the next one is tried.

        Falling back changes which model produced the output, which matters for
        reproducibility, so the model actually used is recorded on the client
        for the report to stamp.
        """
        candidates = [model_name]
        fallback = self.settings.gemini_model_fallback
        if fallback and fallback != model_name:
            candidates.append(fallback)

        last_error: LlmError | None = None
        for index, candidate in enumerate(candidates):
            try:
                raw = await self._attempt_model(
                    prompt=prompt, model_name=candidate, schema=schema, label=label
                )
            except TransientLlmError as exc:
                last_error = exc
                if index + 1 < len(candidates):
                    logger.warning(
                        "llm.failover",
                        extra={"label": label, "from": candidate, "to": candidates[index + 1]},
                    )
                continue
            self.last_model_used = candidate
            return raw

        raise last_error or LlmError(f"{label}: no model available")

    async def _attempt_model(
        self,
        *,
        prompt: str,
        model_name: str,
        schema: dict[str, Any] | None,
        label: str,
    ) -> str:
        """Retry one model through transient failures.

        A 503 means the request never reached the model, so it does not count
        against the per-analysis call budget — though it is still recorded
        against the daily quota, because the vendor counts it.
        """
        last: TransientLlmError | None = None

        for attempt in range(self.transient_retries + 1):
            waited = await self.bucket.acquire()
            if waited > 0:
                logger.info("llm.throttled", extra={"label": label, "waited_s": round(waited, 2)})

            try:
                raw = await self.provider.generate_json(
                    prompt=prompt,
                    model=model_name,
                    schema=schema,
                    temperature=0.0,
                    timeout=self.settings.llm_timeout_seconds,
                )
            except TransientLlmError as exc:
                last = exc
                await self.daily.record(model_name)
                if attempt == self.transient_retries:
                    break
                delay = self.backoff_base_seconds * (2**attempt)
                logger.warning(
                    "llm.transient",
                    extra={
                        "label": label,
                        "status": exc.status,
                        "attempt": attempt + 1,
                        "retry_in_s": delay,
                    },
                )
                await asyncio.sleep(delay)
                continue

            await self.daily.record(model_name, tokens=len(raw) // 4)
            return raw

        raise TransientLlmError(
            f"{label}: {model_name} unavailable after "
            f"{self.transient_retries + 1} attempts — {last}",
            status=last.status if last else None,
        )

    async def embed(
        self,
        texts: list[str],
        *,
        analysis_budget: AnalysisBudget | None = None,
        label: str = "embed",
    ) -> list[list[float]]:
        if not texts:
            return []
        if analysis_budget is not None:
            analysis_budget.consume(label)
        await self.daily.check(self._models)
        await self.bucket.acquire()

        vectors = await self.provider.embed(texts=texts, model=self.settings.gemini_embed_model)
        await self.daily.record(self.settings.gemini_embed_model)
        return vectors


def _summarise(exc: ValidationError, limit: int = 6) -> str:
    """Compact, model-readable validation errors.

    Pydantic's default rendering is long enough to crowd out the prompt itself
    on a retry, so only the first few failures are sent back.
    """
    lines = []
    for err in exc.errors()[:limit]:
        location = ".".join(str(p) for p in err["loc"]) or "(root)"
        lines.append(f"- {location}: {err['msg']}")
    remaining = len(exc.errors()) - limit
    if remaining > 0:
        lines.append(f"- ...and {remaining} more")
    return "\n".join(lines)


def build_client(settings: Settings, daily_budget: DailyBudget) -> LlmClient:
    if not settings.gemini_api_key:
        raise LlmError("GEMINI_API_KEY is not configured")
    return LlmClient(GeminiProvider(settings.gemini_api_key), settings, daily_budget)


__all__ = [
    "GeminiProvider",
    "LlmClient",
    "LlmError",
    "LlmProvider",
    "SchemaViolationError",
    "build_client",
]
