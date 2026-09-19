"""Server-sent events.

The progress screen is a designed part of the product, not a spinner. An
analysis takes fifteen to thirty seconds, and what the user sees during it is
the difference between "this is working through my resume" and "this has frozen".
So the events carry real stage names and real partial results.

**A note on the shape of this, because it differs from the original plan.**

The plan was `POST /analyze` returning an id, then `GET /stream/{id}` to watch
it. That split requires the server to hold a running analysis in memory between
two requests and to hand it to whichever instance the second request lands on.
On Render's free tier — one instance, no shared memory, restarts whenever the
platform feels like it — that buys nothing and adds two failure modes: an
analysis nobody ever attaches to, and a stream that attaches to an analysis that
no longer exists.

Streaming the response to the upload itself has neither problem. One request,
one lifetime, no registry, and it still works unchanged if Roleva ever runs on
more than one instance. The client reads it with `fetch` and a `ReadableStream`
rather than `EventSource`, which is the only real cost — and `EventSource`
cannot send a multipart body anyway, so that path was never going to work
without the split.

A user who closes the tab still keeps their analysis: it is persisted before the
stream ends, and `GET /analyses/{id}` returns it.
"""

from __future__ import annotations

import json
from typing import Any

from roleva.models.report import ProgressEvent

#: Event names in the stream. The client switches on these, so they are part of
#: the API contract and changing one is a breaking change.
EVENT_PROGRESS = "progress"
EVENT_RESULT = "result"
EVENT_ERROR = "error"

#: Sent every few seconds while a long stage runs. Proxies and browsers drop a
#: connection that goes quiet, and the structuring call alone can take twelve
#: seconds.
HEARTBEAT = ": keep-alive\n\n"


def frame(event: str, data: dict[str, Any]) -> str:
    """One SSE frame.

    `json.dumps` with no newlines is not optional here: a raw newline inside the
    data field would terminate the frame early and the client would parse half
    an event as a whole one.
    """
    payload = json.dumps(data, separators=(",", ":"), default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def progress(event: ProgressEvent) -> str:
    return frame(
        EVENT_PROGRESS,
        {
            "analysis_id": event.analysis_id,
            "stage": event.stage.value,
            "message": event.message,
            "percent": event.percent,
            "partial": event.partial,
        },
    )


def result(report_json: dict[str, Any], *, analysis_id: str | None = None) -> str:
    """The finished report. Always the last frame of a successful stream."""
    return frame(EVENT_RESULT, {"analysis_id": analysis_id, "report": report_json})


def error(code: str, message: str) -> str:
    """A failure, as a frame rather than an HTTP status.

    By the time anything is streaming, the status line has already been sent as
    200. The client cannot learn about a failure from the status code, so it has
    to arrive in the stream — and it carries the same written message the
    non-streaming endpoint would have returned, not a stack trace.
    """
    return frame(EVENT_ERROR, {"code": code, "message": message})


SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Render sits behind nginx, which buffers responses by default and would
    # hold every progress event until the analysis finished — turning a live
    # progress screen into a thirty-second pause followed by everything at once.
    "X-Accel-Buffering": "no",
}
