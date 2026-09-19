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
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse

from roleva.api import quota, sse
from roleva.api.auth import CurrentUser, VerifiedUser
from roleva.api.errors import ErrorCode, RolevaError
from roleva.config import Settings, get_settings
from roleva.llm.budget import DailyBudget
from roleva.llm.client import build_client
from roleva.models.report import AnalysisReport, ProgressEvent
from roleva.orchestration.pipeline import AnalysisRequest, Pipeline
from roleva.scoring.engine import load_rubric
from roleva.storage.repository import AnalysisRepository, content_hash
from roleva.storage.samples import record as record_sample
from roleva.storage.supabase import Supabase
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

    await _persist(repository, outcome, combined, job_description)
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
) -> None:
    """Save the analysis, never failing the request if saving fails.

    The user has their report in hand by this point. Losing the history entry is
    a real problem and is logged as one, but raising here would take a finished
    analysis away from them to report a filing error.
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
    except Exception:
        logger.warning("analyze.save_failed", exc_info=True)


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

        await _persist(repository, outcome, combined, job_description)
        await record_sample(
            outcome.report.scores,
            role_family=outcome.report.job.role_family,
            seniority=outcome.report.job.seniority.value,
        )
        yield sse.result(outcome.report.model_dump(mode="json"), analysis_id=analysis_id)

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
