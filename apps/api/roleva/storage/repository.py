"""Reading and writing analyses.

Two product decisions are enforced here rather than merely documented:

**The PDF is never stored.** The user said so explicitly — "the information
dragged out of it is stored", not the file. So the bytes live in memory for the
length of one request and are then gone. What persists is the structured
document: experience, projects, skills, and the spans that point into text the
user gave us. A breach of this database exposes what somebody wrote about their
career, which is bad, but not a folder of downloadable resumes.

**Rows are written with the user's own token.** The service-role key never
touches a table with a `user_id`, so Postgres enforces ownership on the backend
exactly as it does in the browser.

Caching is by content hash. Re-analysing the same resume against the same job
description is the single most likely repeat action a user takes — they fix
something, re-upload, and want to see the number move — and the free tier makes
every avoidable model call worth avoiding. The hash covers only the inputs that
change the output, and lives beside the row it describes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from roleva.api.errors import ErrorCode, RolevaError
from roleva.models.report import AnalysisReport
from roleva.orchestration.pipeline import AnalysisOutcome
from roleva.storage.supabase import Supabase, SupabaseError
from roleva.telemetry.logging import get_logger

logger = get_logger(__name__)

#: Cached analyses older than this are ignored. The rubric can change, models
#: can be swapped, and a month-old score explained by a newer rubric would be
#: a number nobody can reproduce.
CACHE_MAX_AGE_DAYS = 14


def content_hash(*parts: str | bytes) -> str:
    """Stable hash of the inputs that determine an analysis.

    Deliberately includes the rubric version at the call site: a rubric change
    must invalidate every cached score, because the same inputs now produce a
    different answer and serving the old one would break reproducibility.
    """
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part if isinstance(part, bytes) else part.encode("utf-8"))
        digest.update(b"\x00")  # separator, so "ab"+"c" != "a"+"bc"
    return digest.hexdigest()


@dataclass
class StoredAnalysis:
    id: str
    created_at: str
    status: str
    scores: dict[str, Any]
    report: dict[str, Any] | None = None


class AnalysisRepository:
    """Persistence for one signed-in user."""

    def __init__(self, db: Supabase, user_id: str) -> None:
        self.db = db
        self.user_id = user_id

    # ------------------------------------------------------------- write ---

    async def save(
        self,
        outcome: AnalysisOutcome,
        *,
        file_hash: str,
        jd_text: str,
        jd_hash: str,
        label: str | None = None,
    ) -> str:
        """Persist the resume, the job target and the analysis.

        Returns the stored analysis id. Written as three inserts rather than one
        transaction: PostgREST has no transaction across requests, and the cost
        of a partial write here is an orphaned resume row, not a wrong report.
        """
        report = outcome.report

        resume_row = await self.db.insert(
            "resumes",
            {
                "user_id": self.user_id,
                "label": label,
                "file_hash": file_hash,
                # The structured document only. The PDF itself is not stored.
                "document": report.resume.model_dump(mode="json"),
                "schema_version": report.resume.schema_version,
                "parse_confidence": report.scores.overall.confidence,
                "page_count": report.resume.page_count,
            },
        )
        job_row = await self.db.insert(
            "job_targets",
            {
                "user_id": self.user_id,
                "title": report.job.title,
                "company": report.job.company,
                "role_family": report.job.role_family,
                "seniority": report.job.seniority.value,
                "jd_text": jd_text,
                "jd_hash": jd_hash,
                "requirements": [r.model_dump(mode="json") for r in report.job.requirements],
            },
        )

        analysis_row = await self.db.insert(
            "analyses",
            {
                "user_id": self.user_id,
                "resume_id": _id_of(resume_row),
                "job_target_id": _id_of(job_row),
                "status": report.status.value,
                "report": report.model_dump(mode="json"),
                "scores": report.scores.model_dump(mode="json"),
                "rubric_version": report.rubric_version,
                "prompt_version": report.prompt_version,
                "llm_call_count": outcome.llm_calls,
                "duration_ms": int(outcome.log.total_ms),
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )

        analysis_id = _id_of(analysis_row)
        logger.info("analysis.saved", analysis_id=analysis_id, llm_calls=outcome.llm_calls)
        return analysis_id

    # -------------------------------------------------------------- read ---

    async def list(self, *, limit: int = 20, offset: int = 0) -> list[StoredAnalysis]:
        """The user's history, newest first.

        The full report is deliberately not selected: a history list needs the
        scores and the date, and shipping ten complete reports to render ten
        rows is wasted bandwidth on a free tier.
        """
        rows = await self.db.select(
            "analyses",
            columns="id,created_at,status,scores",
            filters={"user_id": f"eq.{self.user_id}"},
            order="created_at.desc",
            limit=limit,
            offset=offset,
        )
        return [
            StoredAnalysis(
                id=row["id"],
                created_at=row["created_at"],
                status=row["status"],
                scores=row.get("scores") or {},
            )
            for row in rows
        ]

    async def get(self, analysis_id: str) -> AnalysisReport:
        """One full report.

        The user filter is applied as well as the id. RLS would refuse another
        user's row anyway; asking for both means a misconfigured policy cannot
        turn a guessed id into somebody else's resume.
        """
        rows = await self.db.select(
            "analyses",
            columns="id,report,status",
            filters={"id": f"eq.{analysis_id}", "user_id": f"eq.{self.user_id}"},
            limit=1,
        )
        if not rows or not rows[0].get("report"):
            raise RolevaError(ErrorCode.NOT_FOUND)
        return AnalysisReport.model_validate(rows[0]["report"])

    async def find_cached(self, *, combined_hash: str) -> AnalysisReport | None:
        """A recent analysis of exactly these inputs, if one exists.

        A miss is never an error. If the lookup itself fails, the analysis runs
        normally — a broken cache must cost latency, never a result.
        """
        try:
            rows = await self.db.select(
                "analyses",
                columns="id,report,created_at",
                filters={
                    "user_id": f"eq.{self.user_id}",
                    "content_hash": f"eq.{combined_hash}",
                    "status": "eq.complete",
                },
                order="created_at.desc",
                limit=1,
            )
        except SupabaseError:
            logger.warning("cache.lookup_failed")
            return None

        if not rows or not rows[0].get("report"):
            return None

        if _age_days(rows[0].get("created_at")) > CACHE_MAX_AGE_DAYS:
            return None

        logger.info("cache.hit", analysis_id=rows[0]["id"])
        return AnalysisReport.model_validate(rows[0]["report"])

    # ------------------------------------------------------------ delete ---

    async def delete(self, analysis_id: str) -> None:
        """Remove one analysis.

        A real delete, not a flag. The user asked for their data to be gone, and
        a soft delete would mean it is not.
        """
        await self.get(analysis_id)  # 404 before deleting something not theirs
        await self.db.delete(
            "analyses",
            filters={"id": f"eq.{analysis_id}", "user_id": f"eq.{self.user_id}"},
        )
        logger.info("analysis.deleted", analysis_id=analysis_id)


def _id_of(row: dict[str, Any] | None) -> str:
    if not row or "id" not in row:
        raise SupabaseError(500, "insert returned no id")
    return str(row["id"])


def _age_days(timestamp: str | None) -> float:
    if not timestamp:
        return float("inf")
    try:
        created = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    return (datetime.now(UTC) - created).total_seconds() / 86_400
