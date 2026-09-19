"""Error reporting, with the one rule that matters: no resume ever leaves.

Sentry is genuinely useful for a service nobody is watching at 3am, and it is
also the easiest way to accidentally ship somebody's employment history to a
third party. Its defaults capture request bodies, headers, cookies and local
variables — and on this service the request body *is* a resume, and a local
variable two frames down is the text extracted from it.

So the integration is subtractive. Everything that could carry user content is
removed before an event is sent, and what is left is the thing an error report
is actually for: where it broke and what kind of error it was.

What is sent:
  * exception type, message and stack frames (without local variables)
  * the route, method and status
  * the request id, so a report can be matched to a log line
  * the user id, which is a UUID

What is never sent: the request body, query string, headers, cookies, local
variables, or breadcrumbs — Roleva's logs carry stage names and durations, but
a breadcrumb from a library might carry an outbound prompt.

The integration is optional at both levels. Without `sentry-sdk` installed, or
without a DSN configured, this is a no-op and the service runs unchanged.
"""

from __future__ import annotations

from typing import Any

from roleva.config import Settings
from roleva.telemetry.logging import get_logger

logger = get_logger(__name__)

#: Request fields that can hold user content. Removed wholesale rather than
#: filtered, because a redactor that misses one case is worse than no field.
_STRIPPED_REQUEST_KEYS = ("data", "cookies", "headers", "query_string", "env")


def _scrub(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Remove anything that could carry a resume, then send what is left."""
    request = event.get("request")
    if isinstance(request, dict):
        for key in _STRIPPED_REQUEST_KEYS:
            request.pop(key, None)

    # Breadcrumbs come from libraries we do not control; an httpx breadcrumb
    # can hold an outbound prompt. Roleva's own structured logs cover the same
    # ground without the risk.
    event.pop("breadcrumbs", None)

    # Local variables in a stack frame routinely hold the extracted text.
    for exception in (event.get("exception") or {}).get("values", []):
        for frame in (exception.get("stacktrace") or {}).get("frames", []):
            frame.pop("vars", None)

    user = event.get("user")
    if isinstance(user, dict):
        # Keep the id — a UUID, and the only way to tell "one user hit this
        # forty times" from "forty users did". Drop everything else.
        event["user"] = {"id": user.get("id")} if user.get("id") else None

    return event


def configure_error_reporting(settings: Settings) -> bool:
    """Start Sentry if it is installed and configured. Returns whether it ran."""
    if not settings.sentry_dsn:
        return False

    try:
        # Optional dependency: the service runs without it, and Sentry is only
        # useful once there is a deployment nobody is watching.
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:
        logger.info("sentry.not_installed")
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        # The single most important setting here. True would attach request
        # bodies and user details automatically.
        send_default_pii=False,
        # Traces cost quota and would add little: the per-stage timings in the
        # structured logs already show where an analysis spends its time.
        traces_sample_rate=0.0,
        max_breadcrumbs=0,
        before_send=_scrub,
    )
    logger.info("sentry.enabled", environment=settings.environment)
    return True
