"""Roleva API entrypoint."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from roleva.api.auth import CurrentUser
from roleva.api.errors import RolevaError
from roleva.api.routes import router
from roleva.config import get_settings
from roleva.storage.supabase import Supabase
from roleva.telemetry.errors import configure_error_reporting
from roleva.telemetry.logging import configure, get_logger

settings = get_settings()
configure(settings.log_level)
configure_error_reporting(settings)
logger = get_logger(__name__)

app = FastAPI(
    title="Roleva API",
    version="0.1.0",
    description="Evidence-based resume analysis.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
    """Tag every log line in a request with a shared id and timing.

    Only the path, method, status and duration are recorded — never the body,
    which for this service is somebody's resume.
    """
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    logger.info(
        "http.request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=elapsed_ms,
    )
    response.headers["x-request-id"] = request_id
    return response


@app.exception_handler(RolevaError)
async def roleva_error_handler(_: Request, exc: RolevaError) -> JSONResponse:
    http_exc = exc.to_http()
    logger.warning("request.rejected", code=exc.code.value, status=http_exc.status_code)
    return JSONResponse(status_code=http_exc.status_code, content=http_exc.detail)


app.include_router(router)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness probe. Touches nothing, so it answers even when the DB is down."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/warmup")
async def warmup() -> dict[str, Any]:
    """Wake both free tiers before the user needs them.

    Two things sleep, not one. Render suspends an idle instance and takes
    roughly fifty seconds to cold-start it; Supabase pauses an idle project and
    takes several seconds on its first query. A health check that touches no
    database wakes only half of what an analysis needs.

    So this also runs the cheapest possible query. The frontend calls it the
    moment somebody lands on the upload page — during the sixty-odd seconds they
    spend choosing a file and pasting a job description, which is exactly the
    window both services need.

    Unauthenticated on purpose: requiring a token would mean the wake-up could
    not happen until after sign-in, which is most of the wait it exists to
    remove. It reads no rows and reveals nothing.
    """
    database = "skipped"
    if settings.supabase_url and settings.supabase_service_role_key:
        try:
            db = Supabase(service_role=True, settings=settings)
            # limit=0 returns no rows. The point is the round trip, not the data.
            await db.select("cohort_stats", columns="role_family", limit=0)
            database = "awake"
        except Exception:
            # A sleeping project can refuse the first query and accept the
            # next. Reporting the attempt is useful; failing the probe is not.
            logger.info("warmup.db_unavailable")
            database = "waking"

    return {"status": "ok", "database": database}


@app.get("/me")
async def me(user: CurrentUser) -> dict[str, Any]:
    """Confirms a token is valid. Returns the user id only — the backend has no
    reason to echo an email address back to a client that already has it."""
    return {"id": user.id, "email_verified": user.email_verified}
