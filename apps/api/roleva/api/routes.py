"""HTTP endpoints.

Thin by design. Every route does the same four things — authorise, enforce
limits, call the pipeline, persist — and nothing that decides an analysis
happens here. A route that contained scoring logic would be a route nobody could
test without HTTP.

Upload handling deserves one note. The file is read into memory, validated, and
never written to disk. Roleva's stated promise is that the PDF is not kept, and
the simplest way to keep that promise is to give the bytes nowhere to go: no
temp file, no upload directory, no object storage bucket.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from roleva.api import quota, sse
from roleva.api.auth import CurrentUser, VerifiedUser
from roleva.api.errors import ErrorCode, RolevaError
from roleva.config import Settings, get_settings
from roleva.llm.budget import DailyBudget
from roleva.llm.client import build_client
from roleva.models.report import AnalysisReport, ProgressEvent
from roleva.orchestration.pipeline import AnalysisRequest, Pipeline
from roleva.scoring.engine import load_rubric
from roleva.sharing import links, redaction
from roleva.sharing.redaction import Visibility
from roleva.sharing.redaction import describe as describe_visibility
from roleva.storage.repository import AnalysisRepository, content_hash
from roleva.storage.samples import record as record_sample
from roleva.storage.supabase import Supabase, SupabaseError
from roleva.storage.usage import build_usage_store
from roleva.telemetry.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

#: Read in chunks so a file claiming to be 2 MB in its headers cannot become
#: 900 MB in memory. The limit is enforced on what actually arrives.
_CHUNK = 64 * 1024

#: How long a stage may run silently before a keep-alive is sent. Shorter than
#: any proxy idle timeout worth worrying about, longer than any real gap
#: between events.
HEARTBEAT_SECONDS = 5.0


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header.removeprefix("Bearer ").strip()


def _client_ip(request: Request) -> str | None:
    """The caller's address, trusting Render's proxy header.

    Only the first entry of X-Forwarded-For is used: the rest are appended by
    intermediaries and a client can put whatever it likes in them.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


async def _read_upload(upload: UploadFile, settings: Settings) -> bytes:
    """Read the upload, refusing anything over the limit as it arrives."""
    chunks: list[bytes] = []
    total = 0

    while chunk := await upload.read(_CHUNK):
        total += len(chunk)
        if total > settings.max_upload_bytes:
            raise RolevaError(ErrorCode.FILE_TOO_LARGE)
        chunks.append(chunk)

    if not total:
        raise RolevaError(ErrorCode.PDF_EMPTY)
    return b"".join(chunks)


def _db(request: Request) -> Supabase:
    return Supabase(token=_bearer(request), settings=get_settings())


@router.post("/analyze", response_model=AnalysisReport)
async def analyze(
    request: Request,
    user: VerifiedUser,
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File(description="The resume, as a PDF")],
    job_description: Annotated[str, Form(description="The full job posting text")],
) -> AnalysisReport:
    """Analyse one resume against one job description.

    Synchronous. At fewer than a hundred analyses a day there is no queue worth
    running, and a request that returns the finished report is far simpler to
    reason about than a job id the client has to poll.
    """
    db = _db(request)

    await quota.check_daily_capacity(db, settings)
    await quota.consume(
        db,
        quota.windows_for(user_id=user.id, client_ip=_client_ip(request), settings=settings),
    )

    pdf_bytes = await _read_upload(file, settings)
    repository = AnalysisRepository(db, user.id)

    # The rubric version is part of the key: new weights must produce a new
    # analysis rather than replaying a score the current rubric cannot explain.
    combined = content_hash(pdf_bytes, job_description, load_rubric()["version"])

    cached = await repository.find_cached(combined_hash=combined)
    if cached is not None:
        logger.info("analyze.cached", user_id=user.id)
        return cached

    # The daily budget is shared state, not per-request state: it is read from
    # and written to Postgres so a restart cannot reset the free tier's count.
    budget = DailyBudget(build_usage_store(settings), settings.llm_max_rpd)
    pipeline = Pipeline(client=build_client(settings, budget), settings=settings)
    outcome = await pipeline.run(
        AnalysisRequest(
            analysis_id=uuid.uuid4().hex,
            pdf_bytes=pdf_bytes,
            job_description=job_description,
            filename=file.filename,
            user_id=user.id,
        )
    )

    # The bytes have done their work. Dropping the reference here is not a
    # security control on its own, but it keeps the window short and states the
    # intent plainly for anyone editing this function later.
    del pdf_bytes

    stored_id = await _persist(repository, outcome, combined, job_description)
    if stored_id:
        # The report's own id is the route it lives at.
        outcome.report.id = stored_id
    await record_sample(
        outcome.report.scores,
        role_family=outcome.report.job.role_family,
        seniority=outcome.report.job.seniority.value,
    )
    return outcome.report


async def _persist(
    repository: AnalysisRepository,
    outcome: Any,
    combined: str,
    job_description: str,
) -> str | None:
    """Save the analysis and return the id it was stored under.

    **That return value matters.** The pipeline generates its own id for the run,
    but Postgres assigns the row a `gen_random_uuid()` of its own — so the two
    are different, and the stored one is the only one `/analyses/{id}` can find.
    Emitting the pipeline's id sent the client to a report that did not exist,
    which is exactly what the first end-to-end run did.

    Never fails the request. The user has their report in hand by this point;
    losing the history entry is a real problem and is logged as one, but raising
    here would take a finished analysis away from them to report a filing error.
    """
    try:
        analysis_id = await repository.save(
            outcome,
            file_hash=combined,
            jd_text=job_description,
            jd_hash=content_hash(job_description),
        )
        await repository.db.update(
            "analyses",
            filters={"id": f"eq.{analysis_id}"},
            values={"content_hash": combined},
        )
        return analysis_id
    except Exception:
        logger.warning("analyze.save_failed", exc_info=True)
        return None


@router.post("/analyze/stream")
async def analyze_stream(
    request: Request,
    user: VerifiedUser,
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File(description="The resume, as a PDF")],
    job_description: Annotated[str, Form(description="The full job posting text")],
) -> StreamingResponse:
    """The same analysis, with progress events while it runs.

    Everything that can be rejected is rejected *before* the stream opens, so a
    quota error is still an HTTP 429 the client can handle normally. Once the
    first byte is sent the status is 200 for good, and any later failure has to
    travel as an error frame instead.
    """
    db = _db(request)

    await quota.check_daily_capacity(db, settings)
    await quota.consume(
        db,
        quota.windows_for(user_id=user.id, client_ip=_client_ip(request), settings=settings),
    )
    pdf_bytes = await _read_upload(file, settings)

    repository = AnalysisRepository(db, user.id)
    combined = content_hash(pdf_bytes, job_description, load_rubric()["version"])
    analysis_id = uuid.uuid4().hex

    async def stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()

        async def emit(event: ProgressEvent) -> None:
            await queue.put(event)

        cached = await repository.find_cached(combined_hash=combined)
        if cached is not None:
            # Still emitted as a stream, so the client has one code path. The
            # progress screen simply completes immediately.
            logger.info("analyze.cached", user_id=user.id)
            yield sse.frame(
                sse.EVENT_PROGRESS,
                {
                    "analysis_id": cached.id,
                    "stage": "done",
                    "message": "Loaded your previous analysis of this resume",
                    "percent": 100,
                    "partial": None,
                },
            )
            # `cached.id` is the row id: the repository stamps it on read, so a
            # cache hit navigates to a route that resolves.
            yield sse.result(cached.model_dump(mode="json"), analysis_id=cached.id)
            return

        budget = DailyBudget(build_usage_store(settings), settings.llm_max_rpd)
        pipeline = Pipeline(client=build_client(settings, budget), settings=settings, emit=emit)
        work = asyncio.create_task(
            pipeline.run(
                AnalysisRequest(
                    analysis_id=analysis_id,
                    pdf_bytes=pdf_bytes,
                    job_description=job_description,
                    filename=file.filename,
                    user_id=user.id,
                )
            )
        )

        # Drain events as they are produced, with a heartbeat whenever a stage
        # runs long enough for a proxy to consider the connection idle.
        while not work.done() or not queue.empty():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                yield sse.HEARTBEAT
                continue
            yield sse.progress(event)

        try:
            outcome = await work
        except RolevaError as exc:
            yield sse.error(exc.code.value, exc.message)
            return
        except Exception:
            logger.exception("analyze.stream_failed")
            failure = RolevaError(ErrorCode.ANALYSIS_FAILED)
            yield sse.error(failure.code.value, failure.message)
            return

        stored_id = await _persist(repository, outcome, combined, job_description)
        if stored_id:
            outcome.report.id = stored_id
        await record_sample(
            outcome.report.scores,
            role_family=outcome.report.job.role_family,
            seniority=outcome.report.job.seniority.value,
        )
        # The stored id, because that is the one the report can be fetched by.
        # `None` means the save failed, and the client shows a message rather
        # than navigating to a route that cannot resolve.
        yield sse.result(outcome.report.model_dump(mode="json"), analysis_id=stored_id)

    return StreamingResponse(stream(), headers=sse.SSE_HEADERS)


@router.get("/analyses")
async def list_analyses(
    request: Request,
    user: CurrentUser,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """The signed-in user's analysis history, newest first."""
    repository = AnalysisRepository(_db(request), user.id)
    stored = await repository.list(limit=min(limit, 50), offset=offset)
    return {
        "analyses": [
            {
                "id": item.id,
                "created_at": item.created_at,
                "status": item.status,
                "scores": item.scores,
            }
            for item in stored
        ]
    }


@router.get("/analyses/{analysis_id}", response_model=AnalysisReport)
async def get_analysis(request: Request, user: CurrentUser, analysis_id: str) -> AnalysisReport:
    repository = AnalysisRepository(_db(request), user.id)
    return await repository.get(analysis_id)


@router.delete("/analyses/{analysis_id}", status_code=204)
async def delete_analysis(request: Request, user: CurrentUser, analysis_id: str) -> None:
    """Delete an analysis permanently.

    No soft delete. When somebody asks for their resume data to be removed, a
    row marked `deleted = true` is not removal.
    """
    repository = AnalysisRepository(_db(request), user.id)
    await repository.delete(analysis_id)


@router.get("/me/quota")
async def quota_remaining(
    request: Request,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """How many analyses the user has left today.

    Read without incrementing — `bump_rate_limit` is the only thing that counts,
    and asking how many you have left must not spend one. The counter is written
    by that function and simply read here.
    """
    db = _db(request)
    used = 0

    try:
        rows = await db.select(
            "rate_limits",
            columns="count",
            filters={
                "key": f"eq.user:{user.id}",
                "window_start": f"eq.{quota.day_window().isoformat()}",
            },
            limit=1,
        )
        used = int(rows[0]["count"]) if rows else 0
    except Exception:
        # A quota display that cannot be read is not worth failing a page over.
        logger.info("quota.read_failed")

    limit = settings.user_daily_analysis_quota
    return {"used": min(used, limit), "limit": limit, "remaining": max(0, limit - used)}


@router.get("/me/export")
async def export_my_data(request: Request, user: CurrentUser) -> dict[str, Any]:
    """Everything Roleva holds about this user, as JSON.

    A data-export endpoint is only honest if it returns *everything*, so this
    reads every user-owned table rather than a curated subset. It runs with the
    caller's own token, so RLS decides what comes back — which means the export
    cannot accidentally include somebody else's row even if a filter were wrong.

    `score_samples` is deliberately absent, and its absence is the point: those
    rows carry no user id, so there is nothing to attribute to anyone. Saying so
    here is more useful than silently omitting them.
    """
    db = _db(request)

    tables = {
        "profile": ("profiles", f"eq.{user.id}", "id"),
        "resumes": ("resumes", f"eq.{user.id}", "user_id"),
        "job_targets": ("job_targets", f"eq.{user.id}", "user_id"),
        "analyses": ("analyses", f"eq.{user.id}", "user_id"),
        "share_links": ("share_links", f"eq.{user.id}", "user_id"),
    }

    export: dict[str, Any] = {
        "exported_at": datetime.now(UTC).isoformat(),
        "user_id": user.id,
        "note": (
            "This is everything Roleva stores that is linked to your account. "
            "Your uploaded PDFs are not here because they are never stored — only "
            "the structured information read out of them. Anonymous score samples "
            "are not here either: they carry no user id, so nothing in them can be "
            "attributed to you."
        ),
    }

    for name, (table, value, column) in tables.items():
        try:
            export[name] = await db.select(table, filters={column: value})
        except SupabaseError:
            # Reporting the failure beats silently returning a short export that
            # looks complete.
            export[name] = {"error": "could not be read"}
            logger.warning("export.table_failed", table=table)

    return export


@router.delete("/me", status_code=204)
async def delete_my_account(request: Request, user: CurrentUser) -> None:
    """Delete the account and everything attached to it.

    Uses the service-role key, which is the one place a user-owned deletion
    legitimately needs it: removing a row from `auth.users` is an admin
    operation, and every table's foreign key cascades from there. So one call
    removes the profile, the resumes, the job targets, the analyses and the
    share links.

    A real delete, not a flag. Someone asking for their resume data to be
    removed is not asking for a column to be set to true.
    """
    settings = get_settings()
    admin = Supabase(service_role=True, settings=settings)

    if not admin.configured:
        raise RolevaError(ErrorCode.ANALYSIS_FAILED, "Account deletion is unavailable.")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.delete(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users/{user.id}",
            headers={
                "apikey": settings.supabase_service_role_key,
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
            },
        )

    if response.status_code >= 400:
        logger.error("account.delete_failed", status=response.status_code)
        raise RolevaError(
            ErrorCode.ANALYSIS_FAILED,
            "We couldn't delete your account. Please try again, or contact support.",
        )

    logger.info("account.deleted", user_id=user.id)


# ------------------------------------------------------------------ sharing ---


class ShareRequest(BaseModel):
    """What the owner is choosing when they create a link."""

    analysis_id: str
    visibility: Visibility = Visibility.FULL_REDACTED
    expires_in_days: int | None = None


@router.post("/shares", status_code=201)
async def create_share(request: Request, user: CurrentUser, body: ShareRequest) -> dict[str, Any]:
    """Create a share link for one of the caller's analyses.

    Written with the caller's own token, so RLS refuses a link for somebody
    else's analysis. The ownership check is the database's.
    """
    link = await links.create(
        _db(request),
        user_id=user.id,
        analysis_id=body.analysis_id,
        visibility=body.visibility,
        expires_in_days=body.expires_in_days,
    )
    return {
        "token": link.token,
        "visibility": link.visibility.value,
        "expires_at": link.expires_at.isoformat(),
        "description": describe_visibility(link.visibility),
    }


@router.get("/shares")
async def list_shares(request: Request, user: CurrentUser) -> dict[str, Any]:
    found = await links.list_for_user(_db(request), user.id)
    return {
        "shares": [
            {
                "token": link.token,
                "analysis_id": link.analysis_id,
                "visibility": link.visibility.value,
                "expires_at": link.expires_at.isoformat(),
                "view_count": link.view_count,
                "active": link.active,
                "revoked": link.revoked,
            }
            for link in found
        ]
    }


@router.delete("/shares/{token}", status_code=204)
async def revoke_share(request: Request, user: CurrentUser, token: str) -> None:
    """Revoke immediately. The next read of this token is a 404."""
    await links.revoke(_db(request), user_id=user.id, token=token)


@router.get("/shared/{token}", response_model=AnalysisReport)
async def read_shared(token: str, response: Response) -> AnalysisReport:
    """Read a shared report. No authentication — the token is the authorisation.

    **The redaction happens here**, before the report is serialised, so what a
    reader can see and what a reader can fetch are the same thing. Nothing is
    hidden in CSS.

    Expired, revoked and never-existed all return the same 404: telling a holder
    of an old link that it used to be real is information the owner did not
    agree to share.
    """
    link = await links.resolve(token)

    settings = get_settings()
    admin = Supabase(service_role=True, settings=settings)
    rows = await admin.select(
        "analyses",
        columns="id,report",
        filters={"id": f"eq.{link.analysis_id}"},
        limit=1,
    )
    if not rows or not rows[0].get("report"):
        raise RolevaError(ErrorCode.NOT_FOUND)

    report = AnalysisReport.model_validate(rows[0]["report"])
    report.id = str(rows[0]["id"])

    await links.record_view(token)

    # A shared report contains somebody's resume. It must never be indexed, and
    # the header is set here as well as in the page's metadata because a crawler
    # fetching the JSON never sees a <meta> tag.
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers["Cache-Control"] = "private, no-store"

    return redaction.apply(report, link.visibility)
