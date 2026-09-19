"""Stage isolation.

The claim this file checks is the one a user experiences: when part of the
analysis fails, they still get the parts that worked, and the report says which
parts are missing rather than quietly presenting a thinner answer as a complete
one.
"""

from __future__ import annotations

import pytest

from roleva.api.errors import ErrorCode, RolevaError
from roleva.models.report import Stage
from roleva.orchestration.stages import (
    CRITICALITY,
    MESSAGES,
    PROGRESS,
    Criticality,
    StageLog,
    describe,
    message_for,
    progress_for,
    run_stage,
)


async def _works() -> str:
    return "value"


async def _explodes() -> str:
    raise RuntimeError("upstream is down")


async def _rejects() -> str:
    raise RolevaError(ErrorCode.PDF_ENCRYPTED)


class TestTheCriticalityTable:
    def test_every_stage_declares_its_failure_behaviour(self) -> None:
        """A new stage must state what its failure costs in order to exist."""
        for stage in Stage:
            if stage is Stage.DONE:
                continue
            assert stage in CRITICALITY, f"{stage.value} has no criticality"

    def test_every_stage_has_a_message_and_a_percentage(self) -> None:
        for stage in Stage:
            assert stage in MESSAGES
            assert stage in PROGRESS

    def test_progress_only_moves_forward(self) -> None:
        """A bar that goes backwards reads as a bug, whatever the truth is."""
        order = [stage for stage in Stage]
        percentages = [PROGRESS[stage] for stage in order]
        assert percentages == sorted(percentages)

    def test_done_is_the_only_hundred(self) -> None:
        assert PROGRESS[Stage.DONE] == 100
        assert all(PROGRESS[s] < 100 for s in Stage if s is not Stage.DONE)

    def test_the_messages_describe_work_not_functions(self) -> None:
        for stage, message in MESSAGES.items():
            assert "_" not in message, f"{stage.value} reads like a function name"
            assert message[0].isupper()

    def test_scoring_is_required(self) -> None:
        """Without scores there is no report, only a document listing."""
        assert CRITICALITY[Stage.SCORING] is Criticality.REQUIRED

    def test_advice_is_allowed_to_fail(self) -> None:
        """Scores and evidence are the product; suggestions are an addition."""
        assert CRITICALITY[Stage.WRITING_ADVICE] is Criticality.DEGRADES


class TestRunStage:
    @pytest.mark.asyncio
    async def test_a_successful_stage_returns_its_value(self) -> None:
        log = StageLog()
        assert await run_stage(Stage.SCORING, log, _works) == "value"
        assert log.degraded == []
        assert log.records[0].ok

    @pytest.mark.asyncio
    async def test_a_required_failure_becomes_a_user_facing_error(self) -> None:
        log = StageLog()
        with pytest.raises(RolevaError) as caught:
            await run_stage(Stage.MATCHING, log, _explodes)
        assert caught.value.code is ErrorCode.ANALYSIS_FAILED
        assert log.degraded == [Stage.MATCHING]

    @pytest.mark.asyncio
    async def test_a_degradable_failure_returns_the_fallback(self) -> None:
        log = StageLog()
        result = await run_stage(Stage.WRITING_ADVICE, log, _explodes, fallback="nothing")
        assert result == "nothing"
        assert log.degraded == [Stage.WRITING_ADVICE]

    @pytest.mark.asyncio
    async def test_a_degradable_failure_does_not_raise(self) -> None:
        log = StageLog()
        assert await run_stage(Stage.ASSESSING_QUALITY, log, _explodes) is None

    @pytest.mark.asyncio
    async def test_a_written_error_message_is_not_replaced(self) -> None:
        """ "This PDF is password-protected" must not become "analysis failed"."""
        log = StageLog()
        with pytest.raises(RolevaError) as caught:
            await run_stage(Stage.VALIDATING, log, _rejects)
        assert caught.value.code is ErrorCode.PDF_ENCRYPTED

    @pytest.mark.asyncio
    async def test_a_rejection_is_still_timed(self) -> None:
        log = StageLog()
        with pytest.raises(RolevaError):
            await run_stage(Stage.VALIDATING, log, _rejects)
        assert len(log.records) == 1
        assert log.records[0].duration_ms >= 0

    @pytest.mark.asyncio
    async def test_the_original_exception_is_kept_as_the_cause(self) -> None:
        """The user sees a written message; the logs keep the real error."""
        log = StageLog()
        with pytest.raises(RolevaError) as caught:
            await run_stage(Stage.MATCHING, log, _explodes)
        assert isinstance(caught.value.__cause__, RuntimeError)

    @pytest.mark.asyncio
    async def test_the_error_type_is_recorded_but_not_its_message(self) -> None:
        """Exception text can quote document content; the type cannot."""
        log = StageLog()
        await run_stage(Stage.WRITING_ADVICE, log, _explodes)
        assert log.records[0].error == "RuntimeError"
        assert "upstream is down" not in str(log.records[0].error)


class TestTelemetry:
    @pytest.mark.asyncio
    async def test_timings_are_recorded_per_stage(self) -> None:
        log = StageLog()
        await run_stage(Stage.SCORING, log, _works)
        await run_stage(Stage.WRITING_ADVICE, log, _explodes)

        summary = describe(log)
        assert set(summary["stages"]) == {"scoring", "writing_advice"}
        assert summary["degraded"] == ["writing_advice"]
        assert summary["total_ms"] == log.total_ms

    @pytest.mark.asyncio
    async def test_the_summary_carries_no_user_content(self) -> None:
        """Telemetry is a place resume text must never leak into."""
        log = StageLog()
        await run_stage(Stage.SCORING, log, _works)
        summary = describe(log)
        assert set(summary) == {"total_ms", "stages", "degraded"}


class TestStageHelpers:
    def test_progress_for_a_known_stage(self) -> None:
        assert progress_for(Stage.DONE) == 100

    def test_message_for_a_known_stage(self) -> None:
        assert message_for(Stage.MATCHING).startswith("Matching")
