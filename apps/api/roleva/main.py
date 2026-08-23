"""Roleva API entrypoint."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from roleva.api.errors import RolevaError
from roleva.config import get_settings

settings = get_settings()
logging.basicConfig(level=settings.log_level)

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


@app.exception_handler(RolevaError)
async def roleva_error_handler(_: Request, exc: RolevaError) -> JSONResponse:
    http_exc = exc.to_http()
    return JSONResponse(status_code=http_exc.status_code, content=http_exc.detail)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness probe.

    Also the warm-up endpoint: the frontend pings this the moment a user lands
    on the upload page, so Render's free-tier instance wakes up during the ~60s
    the user spends picking a file and pasting a job description.
    """
    return {"status": "ok", "environment": settings.environment}
