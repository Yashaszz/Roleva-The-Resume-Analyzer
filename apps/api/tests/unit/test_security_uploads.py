"""9.1 — what happens when the upload is hostile.

A resume analyser accepts arbitrary binary files from anonymous-ish users and
hands them to a C parsing library. That is the largest attack surface in the
product, and the rule is the same for every case here: **refuse in bounded time
with a written message.** Never hang, never exhaust memory, never crash the
worker, never surface a stack trace.

The cases are the ones that actually get tried:

* a decompression bomb — a small file whose streams expand to gigabytes
* a polyglot — a valid PDF that is also valid HTML, aimed at whatever renders
  it next
* structural damage — truncated files, broken xref tables, absurd page counts
* a file that is not a PDF at all but says it is

Each one is built here rather than committed, so the suite carries no hostile
binaries and a reader can see exactly what is being tested.
"""

from __future__ import annotations

import time
import zlib

import pytest

from roleva.api.errors import RolevaError
from roleva.config import Settings
from roleva.parsing import validators

# Generous: the real budget is a user's patience, and anything that trips this
# on a 1 MB file is a denial-of-service vector whatever it returns.
TIME_BUDGET_SECONDS = 10.0


def _settings() -> Settings:
    return Settings(_env_file=None)


def _minimal_pdf(body: bytes = b"") -> bytes:
    """A structurally valid single-page PDF."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        + body
        + b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )


def _expect_refusal(data: bytes) -> str:
    """Open the file and require a clean refusal, quickly.

    Returns the error code, so a test can assert the user got a *specific*
    message rather than a generic failure.
    """
    started = time.perf_counter()
    try:
        with validators.open_validated(data, _settings()):
            pass
    except RolevaError as error:
        elapsed = time.perf_counter() - started
        assert elapsed < TIME_BUDGET_SECONDS, f"took {elapsed:.1f}s to refuse"
        return error.code.value
    except Exception as unexpected:  # pragma: no cover - this is the failure
        raise AssertionError(
            f"raised {type(unexpected).__name__} instead of a written refusal: {unexpected}"
        ) from unexpected

    raise AssertionError("accepted a file that should have been refused")


class TestDecompressionBombs:
    """A few kilobytes that want to become a few gigabytes."""

    def test_a_highly_compressible_stream_does_not_exhaust_memory(self) -> None:
        # 200 MB of zeroes compresses to a handful of kilobytes.
        payload = zlib.compress(b"\x00" * (200 * 1024 * 1024), level=9)
        assert len(payload) < 250_000, "the bomb did not compress; the test is wrong"

        bomb = _minimal_pdf(
            b"4 0 obj<</Length "
            + str(len(payload)).encode()
            + b"/Filter/FlateDecode>>stream\n"
            + payload
            + b"\nendstream endobj\n"
        )

        # Either refused or parsed harmlessly — both are fine. Hanging,
        # crashing or eating the machine are not, and the time budget plus the
        # absence of an unexpected exception is what this asserts.
        started = time.perf_counter()
        try:
            with validators.open_validated(bomb, _settings()):
                pass
        except RolevaError:
            pass
        assert time.perf_counter() - started < TIME_BUDGET_SECONDS

    def test_many_nested_streams_are_bounded(self) -> None:
        chunk = zlib.compress(b"A" * (5 * 1024 * 1024), level=9)
        body = b""
        for index in range(4, 40):
            body += (
                str(index).encode()
                + b" 0 obj<</Length "
                + str(len(chunk)).encode()
                + b"/Filter/FlateDecode>>stream\n"
                + chunk
                + b"\nendstream endobj\n"
            )

        started = time.perf_counter()
        try:
            with validators.open_validated(_minimal_pdf(body), _settings()):
                pass
        except RolevaError:
            pass
        assert time.perf_counter() - started < TIME_BUDGET_SECONDS


class TestPolyglots:
    """Files that are two things at once."""

    def test_a_pdf_that_is_also_html_is_still_treated_as_a_pdf(self) -> None:
        """The danger is downstream: a file served back as HTML runs its script.

        Roleva never serves an upload back — the bytes are not stored at all —
        but the parse must not be confused by the markup either.
        """
        polyglot = _minimal_pdf(
            b"4 0 obj<</Length 90>>stream\n"
            b"<html><script>alert(document.cookie)</script></html>\n"
            b"endstream endobj\n"
        )
        try:
            with validators.open_validated(polyglot, _settings()) as (_doc, stats):
                assert stats.page_count >= 0
        except RolevaError:
            pass  # Refusing is also a correct outcome.

    def test_a_file_claiming_to_be_a_pdf_is_not_believed(self) -> None:
        """Extension and MIME type are claims. The header is evidence."""
        code = _expect_refusal(b"PK\x03\x04" + b"\x00" * 500)
        assert code in {"not_a_pdf", "pdf_corrupt"}


class TestStructuralDamage:
    def test_a_truncated_file_is_refused(self) -> None:
        full = _minimal_pdf()
        code = _expect_refusal(full[: len(full) // 2])
        assert code in {"pdf_corrupt", "not_a_pdf", "pdf_empty"}

    def test_an_empty_file_is_refused(self) -> None:
        assert _expect_refusal(b"") in {"not_a_pdf", "pdf_empty", "pdf_corrupt"}

    def test_a_header_with_nothing_after_it_is_refused(self) -> None:
        assert _expect_refusal(b"%PDF-1.4\n") in {"pdf_corrupt", "pdf_empty", "not_a_pdf"}

    def test_a_lying_page_count_is_refused_as_corrupt(self) -> None:
        """`/Count 999999` with one real page: the count is a claim too.

        PyMuPDF opens the file happily and then raises "Invalid number of
        pages" the first time anything reads it. That surfaced to the user as
        the generic "analysis failed" until the validator learned to treat a
        damaged structure as a corrupt file.
        """
        liar = (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 999999>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n"
        )
        assert _expect_refusal(liar) == "pdf_corrupt"

    @pytest.mark.parametrize(
        "junk",
        [
            b"%PDF-1.4\n" + b"\xff" * 5000,
            b"%PDF-1.4\n" + b"%" * 5000,
            b"%PDF-1.4\ntrailer<</Root 99 0 R>>\n%%EOF\n",
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 1 0 R>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n",
        ],
    )
    def test_assorted_malformations_fail_cleanly(self, junk: bytes) -> None:
        """No stack traces, no hangs — a written refusal or a harmless parse."""
        started = time.perf_counter()
        try:
            with validators.open_validated(junk, _settings()):
                pass
        except RolevaError:
            pass
        except Exception as unexpected:  # pragma: no cover
            raise AssertionError(f"raised {type(unexpected).__name__}") from unexpected
        assert time.perf_counter() - started < TIME_BUDGET_SECONDS


class TestSizeLimits:
    def test_a_file_over_the_limit_is_refused_before_parsing(self) -> None:
        settings = _settings()
        oversize = b"%PDF-1.4\n" + b"\x00" * (settings.max_upload_bytes + 1024)

        started = time.perf_counter()
        code = None
        try:
            with validators.open_validated(oversize, settings):
                pass
        except RolevaError as error:
            code = error.code.value
        elapsed = time.perf_counter() - started

        assert code == "file_too_large"
        # The size check must come first. Parsing 8 MB of junk to discover it is
        # 8 MB would be the denial-of-service the limit exists to prevent.
        assert elapsed < 2.0, f"took {elapsed:.1f}s to reject on size"
