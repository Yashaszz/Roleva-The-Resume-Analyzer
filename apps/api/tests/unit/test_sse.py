"""The SSE contract.

These frames are parsed by client code that switches on the event name, so the
names and the shape are API surface. The formatting tests look trivial and are
not: a stray newline in a data field ends the frame early, and the client parses
half an event as a whole one.
"""

from __future__ import annotations

import json

from roleva.api import sse
from roleva.api.errors import ErrorCode, RolevaError
from roleva.models.report import ProgressEvent, Stage


def _parse(raw: str) -> tuple[str, dict]:
    lines = [line for line in raw.split("\n") if line]
    event = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
    data = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
    return event, json.loads(data)


class TestFraming:
    def test_a_frame_ends_with_a_blank_line(self) -> None:
        """Without the double newline the client never dispatches the event."""
        assert sse.frame("progress", {"a": 1}).endswith("\n\n")

    def test_newlines_in_content_cannot_break_a_frame(self) -> None:
        """A resume line in a message must not terminate the frame early."""
        raw = sse.frame("progress", {"message": "line one\nline two\r\nline three"})
        body = raw.split("data: ", 1)[1]
        assert body.count("\n") == 2  # the frame terminator only
        _, parsed = _parse(raw)
        assert parsed["message"] == "line one\nline two\r\nline three"

    def test_data_is_valid_json(self) -> None:
        _, parsed = _parse(sse.frame("progress", {"percent": 40}))
        assert parsed["percent"] == 40


class TestProgressFrames:
    def _event(self) -> ProgressEvent:
        return ProgressEvent(
            analysis_id="a1",
            stage=Stage.MATCHING,
            message="Matching your evidence against each requirement",
            percent=65,
        )

    def test_a_progress_frame_carries_the_stage_and_percentage(self) -> None:
        event, data = _parse(sse.progress(self._event()))
        assert event == sse.EVENT_PROGRESS
        assert data["stage"] == "matching"
        assert data["percent"] == 65

    def test_partial_results_travel_with_the_event(self) -> None:
        event = self._event()
        event.partial = {"requirements": 12}
        _, data = _parse(sse.progress(event))
        assert data["partial"] == {"requirements": 12}


class TestResultAndError:
    def test_the_result_frame_carries_the_report(self) -> None:
        event, data = _parse(sse.result({"id": "a1", "verdict": "Competitive"}, analysis_id="a1"))
        assert event == sse.EVENT_RESULT
        assert data["report"]["verdict"] == "Competitive"

    def test_an_error_frame_carries_the_written_message(self) -> None:
        """Inside a stream the status line is already 200; the message must
        still be the one the user would have seen from the plain endpoint."""
        failure = RolevaError(ErrorCode.PDF_ENCRYPTED)
        event, data = _parse(sse.error(failure.code.value, failure.message))
        assert event == sse.EVENT_ERROR
        assert data["code"] == "pdf_encrypted"
        assert "password-protected" in data["message"]

    def test_the_error_message_is_not_a_stack_trace(self) -> None:
        failure = RolevaError(ErrorCode.ANALYSIS_FAILED)
        _, data = _parse(sse.error(failure.code.value, failure.message))
        assert "Traceback" not in data["message"]
        assert data["message"][0].isupper()


class TestHeaders:
    def test_buffering_is_disabled(self) -> None:
        """nginx would otherwise hold every event until the analysis finished."""
        assert sse.SSE_HEADERS["X-Accel-Buffering"] == "no"

    def test_the_content_type_is_the_sse_one(self) -> None:
        assert sse.SSE_HEADERS["Content-Type"] == "text/event-stream"

    def test_responses_are_not_cached_or_transformed(self) -> None:
        assert "no-transform" in sse.SSE_HEADERS["Cache-Control"]

    def test_a_heartbeat_is_a_comment_not_an_event(self) -> None:
        """It must keep the connection open without the client dispatching it."""
        assert sse.HEARTBEAT.startswith(":")
        assert sse.HEARTBEAT.endswith("\n\n")
        assert "event:" not in sse.HEARTBEAT


class TestErrorMessages:
    def test_every_error_code_has_a_written_message(self) -> None:
        """A code with no sentence behind it would reach a user as a raw slug."""
        from roleva.api.errors import MESSAGES

        for code in ErrorCode:
            assert code in MESSAGES, f"{code.value} has no message"
            _, message = MESSAGES[code]
            assert message.strip()
            assert message[0].isupper()
            assert message.rstrip().endswith((".", "!"))

    def test_messages_do_not_blame_the_user_for_our_limits(self) -> None:
        from roleva.api.errors import MESSAGES

        _, capacity = MESSAGES[ErrorCode.CAPACITY_REACHED]
        assert "you" not in capacity.lower().split("'")[0].replace("Please", "")


class TestErrorReportingScrubs:
    """Sentry's defaults would ship a resume. These check they are removed."""

    def _event(self) -> dict:
        return {
            "request": {
                "url": "/analyze",
                "method": "POST",
                "data": "<the entire resume>",
                "headers": {"authorization": "Bearer secret"},
                "cookies": "session=abc",
                "query_string": "job=...",
            },
            "breadcrumbs": [{"message": "POST https://gemini/... prompt=<resume>"}],
            "exception": {
                "values": [{"stacktrace": {"frames": [{"vars": {"text": "<the resume>"}}]}}]
            },
            "user": {"id": "u1", "email": "someone@example.com", "ip_address": "1.2.3.4"},
        }

    def test_the_request_body_never_leaves(self) -> None:
        from roleva.telemetry.errors import _scrub

        scrubbed = _scrub(self._event(), {})
        assert scrubbed is not None
        assert "data" not in scrubbed["request"]

    def test_headers_and_cookies_are_removed(self) -> None:
        from roleva.telemetry.errors import _scrub

        scrubbed = _scrub(self._event(), {})
        assert scrubbed is not None
        assert set(scrubbed["request"]) == {"url", "method"}

    def test_stack_frame_locals_are_removed(self) -> None:
        """A local two frames down holds the extracted resume text."""
        from roleva.telemetry.errors import _scrub

        scrubbed = _scrub(self._event(), {})
        assert scrubbed is not None
        frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
        assert "vars" not in frame

    def test_breadcrumbs_are_dropped_entirely(self) -> None:
        """An httpx breadcrumb can carry the outbound prompt."""
        from roleva.telemetry.errors import _scrub

        scrubbed = _scrub(self._event(), {})
        assert scrubbed is not None
        assert "breadcrumbs" not in scrubbed

    def test_the_user_id_survives_but_nothing_else_does(self) -> None:
        from roleva.telemetry.errors import _scrub

        scrubbed = _scrub(self._event(), {})
        assert scrubbed is not None
        assert scrubbed["user"] == {"id": "u1"}

    def test_no_resume_text_survives_anywhere(self) -> None:
        import json

        from roleva.telemetry.errors import _scrub

        scrubbed = _scrub(self._event(), {})
        assert "resume" not in json.dumps(scrubbed)

    def test_it_is_inert_without_a_dsn(self) -> None:
        from roleva.config import Settings
        from roleva.telemetry.errors import configure_error_reporting

        assert configure_error_reporting(Settings(_env_file=None, sentry_dsn="")) is False
