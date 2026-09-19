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
from roleva.telemetry.logging import configure, get_logger

settings = get_settings()
configure(settings.log_level)
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
    """Liveness probe.

    Also the warm-up endpoint: the frontend pings this the moment a user lands
    on the upload page, so Render's free-tier instance wakes up during the ~60s
    the user spends picking a file and pasting a job description.
    """
    return {"status": "ok", "environment": settings.environment}


@app.get("/me")
async def me(user: CurrentUser) -> dict[str, Any]:
    """Confirms a token is valid. Returns the user id only — the backend has no
    reason to echo an email address back to a client that already has it."""
    return {"id": user.id, "email_verified": user.email_verified}
