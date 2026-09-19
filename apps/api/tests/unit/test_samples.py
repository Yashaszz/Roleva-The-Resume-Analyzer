"""The anonymous score sample write path.

The tests that matter most here are the privacy ones. "No user id" is easy to
assert once and easy to break later, so the payload shape is pinned against the
table's own columns rather than against a list someone can edit to match a bug.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from roleva.models.scoring import Band, Score, ScoreKind, ScoreReport
from roleva.storage.samples import (
    MIN_CONFIDENCE,
    NullSampleWriter,
    ScoreSample,
    SupabaseSampleWriter,
    record,
    refusal_reason,
    sample_from,
)

MIGRATION = Path(__file__).parents[4] / "supabase" / "migrations" / "0001_initial_schema.sql"

FIXED_NOW = datetime(2026, 9, 19, 14, 37, 52, 123456, tzinfo=UTC)


def _clock() -> datetime:
    return FIXED_NOW


def _score(kind: ScoreKind, value: float, confidence: float = 1.0) -> Score:
    return Score(kind=kind, value=value, band=Band.COMPETITIVE, confidence=confidence)


def _report(confidence: float = 1.0) -> ScoreReport:
    return ScoreReport(
        overall=_score(ScoreKind.OVERALL, 73.42, confidence),
        job_match=_score(ScoreKind.JOB_MATCH, 61.78, confidence),
        ats=_score(ScoreKind.ATS, 88.05, confidence),
        quality=_score(ScoreKind.QUALITY, 70.5, confidence),
        must_coverage=0.6667,
        overall_coverage=0.75,
        rubric_version="1.0.0",
    )


def _sample() -> ScoreSample:
    return sample_from(_report(), role_family="software_engineering", seniority="entry", now=_clock)


class TestPrivacy:
    def test_the_payload_carries_no_user_identifier(self) -> None:
        payload = _sample().to_payload()
        for forbidden in ("user_id", "analysis_id", "resume_id", "email", "ip", "session"):
            assert forbidden not in payload

    def test_the_payload_matches_the_table_exactly(self) -> None:
        """Pinned against the schema, so a new column cannot be filled silently.

        If someone adds `user_id` to the table, this test fails before any code
        can start writing to it.
        """
        sql = MIGRATION.read_text(encoding="utf-8")
        body = sql.split("create table if not exists public.score_samples (", 1)[1].split(");", 1)[
            0
        ]
        columns = {
            line.strip().split()[0]
            for line in body.splitlines()
            if line.strip() and not line.strip().startswith("--")
        }
        # id is generated, created_at is written explicitly and truncated.
        assert columns - {"id"} == set(_sample().to_payload())

    def test_the_timestamp_is_truncated_to_the_hour(self) -> None:
        """A precise timestamp is a join key back to the user's analysis."""
        created = _sample().created_at
        assert (created.minute, created.second, created.microsecond) == (0, 0, 0)
        assert created.hour == FIXED_NOW.hour

    def test_scores_are_rounded_to_whole_points(self) -> None:
        payload = _sample().to_payload()
        assert payload["overall"] == 73
        assert payload["job_match"] == 62
        assert payload["ats"] == 88
        assert payload["quality"] == 70

    def test_must_coverage_keeps_two_decimals(self) -> None:
        assert _sample().to_payload()["must_coverage"] == 0.67


class TestRefusal:
    def test_a_confident_report_is_accepted(self) -> None:
        assert refusal_reason(_report()) is None

    def test_a_degraded_report_is_refused(self) -> None:
        """Quality confidence drops to 0.6 when the rubric call fails."""
        reason = refusal_reason(_report(confidence=0.6))
        assert reason is not None
        assert "0.60" in reason

    def test_the_boundary_is_inclusive(self) -> None:
        assert refusal_reason(_report(confidence=MIN_CONFIDENCE)) is None
        assert refusal_reason(_report(confidence=MIN_CONFIDENCE - 0.01)) is not None

    @pytest.mark.asyncio
    async def test_a_refused_report_is_never_written(self) -> None:
        writer = NullSampleWriter()
        written = await record(
            _report(confidence=0.5),
            role_family="software_engineering",
            seniority="entry",
            writer=writer,
        )
        assert written is False
        assert writer.written == []


class TestRecording:
    @pytest.mark.asyncio
    async def test_an_accepted_report_reaches_the_writer(self) -> None:
        writer = NullSampleWriter()
        await record(
            _report(),
            role_family="data_science",
            seniority="intern",
            writer=writer,
            now=_clock,
        )
        assert len(writer.written) == 1
        assert writer.written[0].role_family == "data_science"
        assert writer.written[0].seniority == "intern"

    @pytest.mark.asyncio
    async def test_a_failing_writer_never_raises(self) -> None:
        """Losing a statistic must never cost the user their report."""

        class Broken:
            async def write(self, sample: ScoreSample) -> bool:
                raise RuntimeError("supabase is down")

        assert (
            await record(
                _report(),
                role_family="general",
                seniority="entry",
                writer=Broken(),
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_recording_is_deterministic_given_a_clock(self) -> None:
        first = NullSampleWriter()
        second = NullSampleWriter()
        for writer in (first, second):
            await record(
                _report(),
                role_family="general",
                seniority="entry",
                writer=writer,
                now=_clock,
            )
        assert first.written == second.written


class TestSupabaseWriter:
    def test_it_is_unconfigured_without_a_service_key(self) -> None:
        from roleva.config import Settings

        writer = SupabaseSampleWriter(
            Settings(_env_file=None, supabase_url="https://x.supabase.co")
        )
        assert writer.configured is False

    @pytest.mark.asyncio
    async def test_an_unconfigured_writer_writes_nothing(self) -> None:
        from roleva.config import Settings

        writer = SupabaseSampleWriter(Settings(_env_file=None))
        assert await writer.write(_sample()) is False

    def test_the_endpoint_targets_the_samples_table(self) -> None:
        from roleva.config import Settings

        writer = SupabaseSampleWriter(
            Settings(
                _env_file=None, supabase_url="https://x.supabase.co/", supabase_service_role_key="k"
            )
        )
        assert writer._endpoint == "https://x.supabase.co/rest/v1/score_samples"

    def test_it_asks_for_nothing_back(self) -> None:
        """No row handle is returned, so the process cannot find the row again."""
        from roleva.config import Settings

        writer = SupabaseSampleWriter(
            Settings(
                _env_file=None, supabase_url="https://x.supabase.co", supabase_service_role_key="k"
            )
        )
        assert writer._headers["Prefer"] == "return=minimal"


class TestTheTableItself:
    def test_the_schema_has_no_user_column(self) -> None:
        """The guarantee is structural: there is no column to write a user into."""
        sql = MIGRATION.read_text(encoding="utf-8")
        body = sql.split("create table if not exists public.score_samples (", 1)[1].split(");", 1)[
            0
        ]
        assert "user_id" not in body

    def test_the_table_has_no_policy_so_only_the_service_role_reaches_it(self) -> None:
        sql = MIGRATION.read_text(encoding="utf-8")
        assert "alter table public.score_samples enable row level security;" in sql
        policy_targets = re.findall(r"create policy [^;]*? on (public\.\w+)", sql, re.DOTALL)
        assert "public.score_samples" not in policy_targets
