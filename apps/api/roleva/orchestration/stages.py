"""Stage isolation — the rule that a failure degrades the report, never deletes it.

An analysis is nine stages long and four of them call a model over somebody
else's free tier. Something will fail. The question this module answers is what
the user sees when it does.

The answer is: **as much of the report as still holds.** If the rubric call times
out, the quality score falls back to its counted metrics and says its confidence
dropped. If the advice call fails, the scores and the evidence still arrive. Only
a failure in parsing or matching can end an analysis, because without those there
is nothing left to be right about.

This is implemented as one decision recorded per stage, not as try/except
scattered through the pipeline:

  * `REQUIRED` — the analysis cannot continue. Raises, mapped to a user message.
  * `DEGRADES` — the stage is allowed to fail; the report is marked partial and
    the affected score's confidence drops.
  * `OPTIONAL` — the stage failing changes nothing the user would notice.

Keeping the policy in one table means a new stage has to state its failure
behaviour to exist, rather than inheriting whatever the surrounding try block
happened to do.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from roleva.api.errors import ErrorCode, RolevaError
from roleva.models.report import Stage
from roleva.telemetry.logging import get_logger

logger = get_logger(__name__)


class Criticality(StrEnum):
    REQUIRED = "required"
    DEGRADES = "degrades"
    OPTIONAL = "optional"


#: What each stage's failure costs. Stated once, here, rather than implied by
#: where somebody happened to put a try block.
CRITICALITY: dict[Stage, Criticality] = {
    Stage.VALIDATING: Criticality.REQUIRED,
    Stage.EXTRACTING: Criticality.REQUIRED,
    # The structurer is an LLM call, but a resume that cannot be structured
    # cannot be matched, scored or quoted. There is no partial report to give.
    Stage.STRUCTURING: Criticality.REQUIRED,
    Stage.READING_JOB: Criticality.REQUIRED,
    Stage.MATCHING: Criticality.REQUIRED,
    # Formatting checks are deterministic and local; if they break, the rest of
    # the analysis is unaffected and the ATS score is simply reported as 100
    # with a note that the checks did not run.
    Stage.CHECKING_ATS: Criticality.DEGRADES,
    Stage.ASSESSING_QUALITY: Criticality.DEGRADES,
    Stage.SCORING: Criticality.REQUIRED,
    Stage.WRITING_ADVICE: Criticality.DEGRADES,
}

#: Progress percentages. Deliberately uneven: they track how long each stage
#: actually takes, so the bar does not stall at 40% for eleven seconds.
PROGRESS: dict[Stage, int] = {
    Stage.VALIDATING: 5,
    Stage.EXTRACTING: 15,
    Stage.STRUCTURING: 35,
    Stage.READING_JOB: 45,
    Stage.MATCHING: 65,
    Stage.CHECKING_ATS: 72,
    Stage.ASSESSING_QUALITY: 82,
    Stage.SCORING: 90,
    Stage.WRITING_ADVICE: 97,
    Stage.DONE: 100,
}

#: What the user is told is happening. Written as work they care about rather
#: than as function names.
MESSAGES: dict[Stage, str] = {
    Stage.VALIDATING: "Checking your file",
    Stage.EXTRACTING: "Reading the document",
    Stage.STRUCTURING: "Finding your experience, projects and skills",
    Stage.READING_JOB: "Reading the job description",
    Stage.MATCHING: "Matching your evidence against each requirement",
    Stage.CHECKING_ATS: "Checking how applicant tracking systems will parse this",
    Stage.ASSESSING_QUALITY: "Assessing how your bullets are written",
    Stage.SCORING: "Computing your scores",
    Stage.WRITING_ADVICE: "Writing suggestions",
    Stage.DONE: "Done",
}


@dataclass
class StageRecord:
    """What happened in one stage. Kept whether it succeeded or not."""

    stage: Stage
    ok: bool
    duration_ms: float
    error: str | None = None


@dataclass
class StageLog:
    """The per-stage timing and failure record for one analysis."""

    records: list[StageRecord] = field(default_factory=list)

    @property
    def degraded(self) -> list[Stage]:
        return [record.stage for record in self.records if not record.ok]

    @property
    def total_ms(self) -> float:
        return round(sum(record.duration_ms for record in self.records), 1)

    def timings(self) -> dict[str, float]:
        return {record.stage.value: record.duration_ms for record in self.records}


async def run_stage[T](
    stage: Stage,
    log: StageLog,
    work: Callable[[], Awaitable[T]],
    *,
    fallback: T | None = None,
) -> T | None:
    """Run one stage, recording its outcome and applying its failure policy.

    A REQUIRED stage re-raises. A DEGRADES or OPTIONAL stage returns `fallback`
    and the failure is recorded, so the report can tell the user which part of
    the analysis is missing instead of pretending it was never attempted.
    """
    started = time.perf_counter()
    try:
        result = await work()
    except RolevaError:
        # Already a user-facing failure with a written message. Record the
        # timing, then let it through untouched — rewriting it here would
        # replace a specific explanation with a generic one.
        log.records.append(
            StageRecord(stage=stage, ok=False, duration_ms=_elapsed(started), error="rejected")
        )
        raise
    except Exception as exc:
        elapsed = _elapsed(started)
        log.records.append(
            StageRecord(stage=stage, ok=False, duration_ms=elapsed, error=type(exc).__name__)
        )
        criticality = CRITICALITY.get(stage, Criticality.REQUIRED)

        if criticality is Criticality.REQUIRED:
            logger.error(
                "stage.failed", stage=stage.value, error=type(exc).__name__, duration_ms=elapsed
            )
            raise RolevaError(ErrorCode.ANALYSIS_FAILED) from exc

        logger.warning(
            "stage.degraded", stage=stage.value, error=type(exc).__name__, duration_ms=elapsed
        )
        return fallback

    log.records.append(StageRecord(stage=stage, ok=True, duration_ms=_elapsed(started)))
    return result


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def progress_for(stage: Stage) -> int:
    return PROGRESS.get(stage, 0)


def message_for(stage: Stage) -> str:
    return MESSAGES.get(stage, stage.value.replace("_", " ").capitalize())


def describe(log: StageLog) -> dict[str, Any]:
    """Timing summary for telemetry. Contains no user content by construction."""
    return {
        "total_ms": log.total_ms,
        "stages": log.timings(),
        "degraded": [stage.value for stage in log.degraded],
    }
