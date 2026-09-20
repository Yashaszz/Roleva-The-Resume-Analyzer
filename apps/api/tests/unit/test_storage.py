"""Persistence, caching and rate limiting.

The tests that matter here are about which key reaches which table, what the
cache is allowed to serve, and whether a limiter failure can cost a user their
finished report.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from roleva.api import quota
from roleva.api.errors import ErrorCode, RolevaError
from roleva.config import Settings
from roleva.storage.repository import CACHE_MAX_AGE_DAYS, AnalysisRepository, content_hash
from roleva.storage.supabase import Supabase, SupabaseError

MIGRATIONS = Path(__file__).parents[4] / "supabase" / "migrations"


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "supabase_url": "https://x.supabase.co",
        "supabase_anon_key": "anon-key",
        "supabase_service_role_key": "service-key",
    }
    base.update(overrides)
    return Settings(**base)


class FakeDb:
    """Records calls instead of making them."""

    def __init__(self, *, rows: list[dict[str, Any]] | None = None, fail: bool = False) -> None:
        self.rows = rows if rows is not None else []
        self.fail = fail
        self.inserts: list[tuple[str, dict[str, Any]]] = []
        self.deletes: list[tuple[str, dict[str, str]]] = []
        self.rpcs: list[tuple[str, dict[str, Any]]] = []
        self.rpc_result: Any = 1

    async def insert(self, table: str, row: dict[str, Any], **_: Any) -> dict[str, Any]:
        self.inserts.append((table, row))
        return {"id": f"{table}-id"}

    async def select(self, table: str, **kwargs: Any) -> list[dict[str, Any]]:
        if self.fail:
            raise SupabaseError(500, "boom")
        return self.rows

    async def update(self, table: str, **kwargs: Any) -> None:
        return None

    async def delete(self, table: str, *, filters: dict[str, str]) -> None:
        self.deletes.append((table, filters))

    async def rpc(self, function: str, payload: dict[str, Any]) -> Any:
        self.rpcs.append((function, payload))
        if self.fail:
            raise SupabaseError(500, "boom")
        return self.rpc_result


class TestKeySelection:
    def test_a_user_table_requires_a_user_token(self) -> None:
        """The property the RLS tests prove; enforced here so it cannot regress."""
        with pytest.raises(ValueError, match="user token is required"):
            Supabase(settings=_settings())

    def test_the_service_role_must_be_asked_for_explicitly(self) -> None:
        client = Supabase(service_role=True, settings=_settings())
        assert client._headers()["apikey"] == "service-key"

    def test_a_user_token_is_sent_as_the_bearer(self) -> None:
        client = Supabase(token="user-jwt", settings=_settings())
        headers = client._headers()
        assert headers["Authorization"] == "Bearer user-jwt"
        # The anon key identifies the project; the token identifies the user,
        # and RLS reads the token.
        assert headers["apikey"] == "anon-key"


class TestContentHash:
    def test_the_same_inputs_hash_the_same(self) -> None:
        assert content_hash(b"pdf", "jd", "1.0.0") == content_hash(b"pdf", "jd", "1.0.0")

    def test_different_inputs_hash_differently(self) -> None:
        assert content_hash(b"pdf", "jd") != content_hash(b"pdf", "other jd")

    def test_the_boundary_between_parts_matters(self) -> None:
        """Without a separator, ("ab","c") and ("a","bc") would collide."""
        assert content_hash("ab", "c") != content_hash("a", "bc")

    def test_the_rubric_version_changes_the_hash(self) -> None:
        """A rubric change must invalidate every cached score."""
        assert content_hash(b"pdf", "jd", "1.0.0") != content_hash(b"pdf", "jd", "1.1.0")


class TestCache:
    @pytest.mark.asyncio
    async def test_a_recent_analysis_is_served(self) -> None:
        report = _minimal_report()
        db = FakeDb(rows=[{"id": "a1", "report": report, "created_at": _iso(days_ago=1)}])
        found = await AnalysisRepository(db, "u1").find_cached(combined_hash="h")  # type: ignore[arg-type]
        assert found is not None
        assert found.id == report["id"]

    @pytest.mark.asyncio
    async def test_a_stale_analysis_is_not_served(self) -> None:
        """An old score was computed by a rubric that may no longer exist."""
        db = FakeDb(
            rows=[
                {
                    "id": "a1",
                    "report": _minimal_report(),
                    "created_at": _iso(days_ago=CACHE_MAX_AGE_DAYS + 1),
                }
            ]
        )
        assert await AnalysisRepository(db, "u1").find_cached(combined_hash="h") is None  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_a_miss_is_not_an_error(self) -> None:
        db = FakeDb(rows=[])
        assert await AnalysisRepository(db, "u1").find_cached(combined_hash="h") is None  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_a_broken_cache_costs_latency_not_a_result(self) -> None:
        db = FakeDb(fail=True)
        assert await AnalysisRepository(db, "u1").find_cached(combined_hash="h") is None  # type: ignore[arg-type]


class TestRepository:
    @pytest.mark.asyncio
    async def test_the_pdf_is_never_written(self) -> None:
        """The product promise, asserted against what actually gets inserted."""
        db = FakeDb()
        outcome = _fake_outcome()
        await AnalysisRepository(db, "u1").save(  # type: ignore[arg-type]
            outcome, file_hash="h", jd_text="jd text", jd_hash="jh"
        )

        for table, row in db.inserts:
            for key, value in row.items():
                assert not isinstance(value, bytes), f"{table}.{key} holds raw bytes"
                assert "pdf" not in key.lower() or key == "file_hash"

    @pytest.mark.asyncio
    async def test_all_three_rows_are_written(self) -> None:
        db = FakeDb()
        await AnalysisRepository(db, "u1").save(  # type: ignore[arg-type]
            _fake_outcome(), file_hash="h", jd_text="jd", jd_hash="jh"
        )
        assert [table for table, _ in db.inserts] == ["resumes", "job_targets", "analyses"]

    @pytest.mark.asyncio
    async def test_every_row_carries_the_owner(self) -> None:
        db = FakeDb()
        await AnalysisRepository(db, "u1").save(  # type: ignore[arg-type]
            _fake_outcome(), file_hash="h", jd_text="jd", jd_hash="jh"
        )
        assert all(row["user_id"] == "u1" for _, row in db.inserts)

    @pytest.mark.asyncio
    async def test_a_missing_analysis_is_a_404_not_an_empty_report(self) -> None:
        db = FakeDb(rows=[])
        with pytest.raises(RolevaError) as caught:
            await AnalysisRepository(db, "u1").get("nope")  # type: ignore[arg-type]
        assert caught.value.code is ErrorCode.NOT_FOUND

    @pytest.mark.asyncio
    async def test_delete_is_scoped_to_the_owner(self) -> None:
        db = FakeDb(rows=[{"id": "a1", "report": _minimal_report(), "status": "complete"}])
        await AnalysisRepository(db, "u1").delete("a1")  # type: ignore[arg-type]
        _, filters = db.deletes[0]
        assert filters == {"id": "eq.a1", "user_id": "eq.u1"}

    @pytest.mark.asyncio
    async def test_deleting_something_that_is_not_yours_is_a_404(self) -> None:
        db = FakeDb(rows=[])
        with pytest.raises(RolevaError):
            await AnalysisRepository(db, "u1").delete("someone-elses")  # type: ignore[arg-type]
        assert db.deletes == []


class TestRateLimits:
    def test_the_user_limit_is_checked_before_the_ip_limit(self) -> None:
        """ "You've used your five" beats "your network is busy"."""
        windows = quota.windows_for(user_id="u1", client_ip="1.2.3.4", settings=_settings())
        assert windows[0].key.startswith("user:")
        assert windows[0].code is ErrorCode.QUOTA_EXCEEDED

    def test_the_ip_window_is_hourly_and_the_user_window_daily(self) -> None:
        now = datetime(2026, 9, 20, 14, 37, tzinfo=UTC)
        windows = quota.windows_for(
            user_id="u1", client_ip="1.2.3.4", settings=_settings(), now=now
        )
        assert windows[0].window_start.hour == 0
        assert windows[1].window_start.hour == 14
        assert windows[1].window_start.minute == 0

    def test_no_ip_means_no_ip_window(self) -> None:
        windows = quota.windows_for(user_id="u1", client_ip=None, settings=_settings())
        assert len(windows) == 1

    @pytest.mark.asyncio
    async def test_a_request_under_the_limit_passes(self) -> None:
        db = FakeDb()
        db.rpc_result = 1
        await quota.consume(
            db, quota.windows_for(user_id="u1", client_ip=None, settings=_settings())
        )  # type: ignore[arg-type]
        assert db.rpcs[0][0] == "bump_rate_limit"

    @pytest.mark.asyncio
    async def test_exceeding_the_limit_raises_the_right_code(self) -> None:
        db = FakeDb()
        db.rpc_result = 99
        with pytest.raises(RolevaError) as caught:
            await quota.consume(
                db,  # type: ignore[arg-type]
                quota.windows_for(user_id="u1", client_ip=None, settings=_settings()),
            )
        assert caught.value.code is ErrorCode.QUOTA_EXCEEDED

    @pytest.mark.asyncio
    async def test_the_limit_is_inclusive_of_the_quota(self) -> None:
        """A quota of five means the fifth request works and the sixth does not."""
        db = FakeDb()
        settings = _settings(user_daily_analysis_quota=5)
        windows = quota.windows_for(user_id="u1", client_ip=None, settings=settings)

        db.rpc_result = 5
        await quota.consume(db, windows)  # type: ignore[arg-type]

        db.rpc_result = 6
        with pytest.raises(RolevaError):
            await quota.consume(db, windows)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_a_broken_limiter_fails_open_by_default(self) -> None:
        """A database hiccup must not stop people using the product."""
        db = FakeDb(fail=True)
        await quota.consume(
            db, quota.windows_for(user_id="u1", client_ip=None, settings=_settings())
        )  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_it_can_be_told_to_fail_closed(self) -> None:
        db = FakeDb(fail=True)
        with pytest.raises(RolevaError) as caught:
            await quota.consume(
                db,  # type: ignore[arg-type]
                quota.windows_for(user_id="u1", client_ip=None, settings=_settings()),
                fail_open=False,
            )
        assert caught.value.code is ErrorCode.CAPACITY_REACHED


class TestCapacity:
    @pytest.mark.asyncio
    async def test_capacity_reached_is_its_own_error(self) -> None:
        """Not the user's fault, so not the user's quota message."""
        db = FakeDb(rows=[{"request_count": 250}])
        with pytest.raises(RolevaError) as caught:
            await quota.check_daily_capacity(db, _settings(llm_max_rpd=250))  # type: ignore[arg-type]
        assert caught.value.code is ErrorCode.CAPACITY_REACHED

    @pytest.mark.asyncio
    async def test_usage_is_summed_across_models(self) -> None:
        db = FakeDb(rows=[{"request_count": 100}, {"request_count": 160}])
        with pytest.raises(RolevaError):
            await quota.check_daily_capacity(db, _settings(llm_max_rpd=250))  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_room_left_means_no_error(self) -> None:
        db = FakeDb(rows=[{"request_count": 10}])
        await quota.check_daily_capacity(db, _settings(llm_max_rpd=250))  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_a_failed_check_does_not_block_anybody(self) -> None:
        db = FakeDb(fail=True)
        await quota.check_daily_capacity(db, _settings())  # type: ignore[arg-type]


class TestMigration:
    def test_the_counters_are_incremented_in_postgres(self) -> None:
        """Read-then-write from the app is a race two browser tabs can win."""
        sql = (MIGRATIONS / "0002_cache_and_limits.sql").read_text(encoding="utf-8")
        assert "create or replace function public.bump_rate_limit" in sql
        assert "count = public.rate_limits.count + 1" in sql
        assert "request_count = public.llm_usage.request_count + 1" in sql.replace("  ", " ")

    def test_the_counter_functions_are_not_open_to_everyone(self) -> None:
        sql = (MIGRATIONS / "0002_cache_and_limits.sql").read_text(encoding="utf-8")
        assert "revoke all on function public.bump_rate_limit" in sql
        assert "revoke all on function public.bump_llm_usage" in sql

    def test_the_migration_is_idempotent(self) -> None:
        """The user re-runs these by hand."""
        sql = (MIGRATIONS / "0002_cache_and_limits.sql").read_text(encoding="utf-8")
        assert "add column if not exists" in sql
        assert "create index if not exists" in sql
        for statement in sql.split("create "):
            if statement.startswith("function"):
                raise AssertionError("use 'create or replace function'")


# ------------------------------------------------------------------ helpers ---


def _iso(*, days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def _minimal_report() -> dict[str, Any]:
    from roleva.models.report import AnalysisReport, AnalysisStatus
    from roleva.models.scoring import Band, Score, ScoreKind, ScoreReport

    def score(kind: ScoreKind) -> Score:
        return Score(kind=kind, value=70.0, band=Band.COMPETITIVE)

    report = AnalysisReport(
        id="a1",
        status=AnalysisStatus.COMPLETE,
        created_at=datetime.now(UTC),
        resume={},  # type: ignore[arg-type]
        job={},  # type: ignore[arg-type]
        matches={},  # type: ignore[arg-type]
        ats={},  # type: ignore[arg-type]
        scores=ScoreReport(
            overall=score(ScoreKind.OVERALL),
            job_match=score(ScoreKind.JOB_MATCH),
            ats=score(ScoreKind.ATS),
            quality=score(ScoreKind.QUALITY),
            must_coverage=1.0,
            overall_coverage=1.0,
            rubric_version="1.0.0",
        ),
        rubric_version="1.0.0",
        prompt_version="p1",
    )
    dumped: dict[str, Any] = report.model_dump(mode="json")
    return dumped


def _fake_outcome() -> Any:
    from roleva.models.report import AnalysisReport
    from roleva.orchestration.pipeline import AnalysisOutcome
    from roleva.orchestration.stages import StageLog

    return AnalysisOutcome(
        report=AnalysisReport.model_validate(_minimal_report()),
        log=StageLog(),
        llm_calls=4,
    )


class TestTheStoredIdIsWhatTheClientGets:
    """Found by the first end-to-end run.

    The pipeline generates its own analysis id; Postgres assigns the row a
    `gen_random_uuid()`. They are different, and only the stored one can be
    fetched back. Emitting the pipeline's id sent the browser to a 404 on a
    report that had just been computed successfully.
    """

    @pytest.mark.asyncio
    async def test_save_returns_the_id_postgres_assigned(self) -> None:
        db = FakeDb()
        stored = await AnalysisRepository(db, "u1").save(
            _fake_outcome(), file_hash="h", jd_text="jd", jd_hash="jh"
        )
        # FakeDb echoes "<table>-id"; the point is that it comes from the insert
        # response rather than from anything the caller passed in.
        assert stored == "analyses-id"

    @pytest.mark.asyncio
    async def test_it_is_not_the_id_the_pipeline_generated(self) -> None:
        db = FakeDb()
        outcome = _fake_outcome()
        pipeline_id = outcome.report.id
        stored = await AnalysisRepository(db, "u1").save(
            outcome, file_hash="h", jd_text="jd", jd_hash="jh"
        )
        assert stored != pipeline_id

    @pytest.mark.asyncio
    async def test_the_row_carries_no_client_supplied_id(self) -> None:
        """The database assigns it, so the insert must not name one."""
        db = FakeDb()
        await AnalysisRepository(db, "u1").save(
            _fake_outcome(), file_hash="h", jd_text="jd", jd_hash="jh"
        )
        analyses_row = next(row for table, row in db.inserts if table == "analyses")
        assert "id" not in analyses_row

    @pytest.mark.asyncio
    async def test_a_fetched_report_carries_the_row_id_not_the_stored_one(self) -> None:
        """The report JSON was serialised with the pipeline's id. The row's id
        is the only one that resolves, so it wins on read."""
        stored = _minimal_report()
        stored["id"] = "pipeline-generated-id"
        db = FakeDb(rows=[{"id": "row-id-from-postgres", "report": stored, "status": "complete"}])

        report = await AnalysisRepository(db, "u1").get("row-id-from-postgres")  # type: ignore[arg-type]
        assert report.id == "row-id-from-postgres"

    @pytest.mark.asyncio
    async def test_a_cache_hit_carries_the_row_id_too(self) -> None:
        """The second call site that got this wrong. A cached report navigated
        the browser to the id baked into its JSON, which 404s."""
        stored = _minimal_report()
        stored["id"] = "pipeline-generated-id"
        db = FakeDb(
            rows=[{"id": "row-id-from-postgres", "report": stored, "created_at": _iso(days_ago=1)}]
        )

        report = await AnalysisRepository(db, "u1").find_cached(combined_hash="h")  # type: ignore[arg-type]
        assert report is not None
        assert report.id == "row-id-from-postgres"


class TestRpcWithNoReturnValue:
    """Found by the first live share view.

    `bump_share_view` returns void, so PostgREST answers 204 with an empty
    body. `rpc()` called `.json()` on it unconditionally and raised — which
    turned a view counter into a 500 on the page it was counting.
    """

    @pytest.mark.asyncio
    async def test_a_204_returns_none_rather_than_raising(self) -> None:
        import httpx

        from roleva.storage.supabase import Supabase

        client = Supabase(service_role=True, settings=_settings())

        async def fake_request(method: str, table: str, **kwargs: Any) -> httpx.Response:
            return httpx.Response(204, request=httpx.Request("POST", "http://x"))

        client._request = fake_request  # type: ignore[assignment]
        assert await client.rpc("bump_share_view", {"p_token": "t"}) is None

    @pytest.mark.asyncio
    async def test_an_empty_200_body_also_returns_none(self) -> None:
        import httpx

        from roleva.storage.supabase import Supabase

        client = Supabase(service_role=True, settings=_settings())

        async def fake_request(method: str, table: str, **kwargs: Any) -> httpx.Response:
            return httpx.Response(200, content=b"", request=httpx.Request("POST", "http://x"))

        client._request = fake_request  # type: ignore[assignment]
        assert await client.rpc("noop", {}) is None

    @pytest.mark.asyncio
    async def test_a_real_value_still_comes_back(self) -> None:
        import httpx

        from roleva.storage.supabase import Supabase

        client = Supabase(service_role=True, settings=_settings())

        async def fake_request(method: str, table: str, **kwargs: Any) -> httpx.Response:
            return httpx.Response(200, content=b"7", request=httpx.Request("POST", "http://x"))

        client._request = fake_request  # type: ignore[assignment]
        assert await client.rpc("bump_rate_limit", {}) == 7
