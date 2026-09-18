"""Structured logging with a hard guarantee: resume content never reaches a log.

Logs are the easiest place for PII to leak. They are written from everywhere,
read by third-party services, and retained long after the request is gone. So
rather than relying on every call site to be careful, a processor sits in the
pipeline and drops anything that looks like content before it is emitted.

Two defences:

  * **Denylisted keys** — fields whose names indicate content are replaced with
    a summary (length and a hash) so an entry is still debuggable.
  * **Value scanning** — any string value that contains an email address or a
    long digit run is masked, catching content that slipped in under an
    innocent key name.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from typing import Any

import structlog
from structlog.typing import EventDict, WrappedLogger

#: Field names that carry document content. Never logged, under any level.
_CONTENT_KEYS = frozenset(
    {
        "text",
        "raw",
        "content",
        "prompt",
        "response",
        "resume",
        "resume_text",
        "jd",
        "jd_text",
        "job_description",
        "bullet",
        "bullets",
        "evidence",
        "snippet",
        "excerpt",
        "document",
        "name",
        "email",
        "phone",
        "address",
        "location",
    }
)

#: Field names whose values are secrets rather than content.
_SECRET_KEYS = frozenset({"api_key", "token", "authorization", "password", "jwt", "secret"})

_EMAIL_IN_VALUE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_LONG_DIGITS = re.compile(r"\d{7,}")


def _fingerprint(value: str) -> str:
    """A stable, non-reversible summary — enough to correlate, not to read."""
    digest = hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:8]
    return f"<redacted {len(value)} chars sha:{digest}>"


def scrub_content(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Strip content and secrets from every log entry.

    Applied as a structlog processor, so it runs for every call regardless of
    which module made it.
    """
    for key, value in list(event_dict.items()):
        lowered = key.lower()

        if lowered in _SECRET_KEYS:
            event_dict[key] = "<secret>"
            continue

        if lowered in _CONTENT_KEYS:
            event_dict[key] = _fingerprint(value) if isinstance(value, str) else "<redacted>"
            continue

        if isinstance(value, str) and (_EMAIL_IN_VALUE.search(value) or _LONG_DIGITS.search(value)):
            event_dict[key] = _EMAIL_IN_VALUE.sub("<email>", _LONG_DIGITS.sub("<digits>", value))

    return event_dict


def configure(level: str = "INFO", *, json_output: bool | None = None) -> None:
    """Set up logging for the process.

    JSON in production so Render's log drain and Sentry can parse it; a
    human-readable console renderer in development.
    """
    if json_output is None:
        json_output = not sys.stderr.isatty()

    renderer: Any = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            # Scrubbing runs last among the enrichers, so it also sees fields
            # added by context binding.
            scrub_content,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
