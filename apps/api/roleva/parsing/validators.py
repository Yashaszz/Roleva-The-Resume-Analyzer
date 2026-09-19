"""Upload validation — the gate every PDF passes before any work is done.

Two principles:

**Fail fast.** Every check that can reject a file runs before extraction, and
long before an LLM call. A malformed upload should cost nothing.

**Fail usefully.** Each rejection names the fix rather than the fault. "This
looks like a scanned image — export directly from Word or Google Docs instead
of scanning a printout" is a message someone can act on; "invalid PDF" is not.
Error copy here is product surface, not diagnostics.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from roleva.api.errors import ErrorCode, RolevaError
from roleva.config import Settings
from roleva.parsing import _pymupdf as mu

#: Every PDF begins with this. Checked against the bytes rather than the
#: filename, which anyone can rename.
_PDF_MAGIC = b"%PDF-"

#: An image covering this share of the page is a scan rather than a logo.
_PAGE_COVER_RATIO = 0.55

#: Frequent English function words. Deliberately words that a resume in another
#: language would not contain, and that survive heavy formatting.
_ENGLISH_MARKERS = frozenset(
    {
        "and",
        "the",
        "for",
        "with",
        "from",
        "that",
        "this",
        "using",
        "used",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "as",
        "an",
        "a",
        "is",
        "was",
        "were",
        "developed",
        "built",
        "managed",
        "led",
        "designed",
        "team",
        "experience",
        "skills",
        "education",
        "project",
        "work",
    }
)

_WORD_RE = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class PdfStats:
    """What the validator measured. Carried forward so later stages and the ATS
    checks do not have to re-open the document."""

    page_count: int
    text_chars: int
    image_count: int
    has_page_covering_image: bool
    english_ratio: float

    @property
    def chars_per_page(self) -> float:
        return self.text_chars / self.page_count if self.page_count else 0.0


def english_ratio(text: str) -> float:
    """Share of words that are common English markers.

    A deterministic heuristic rather than a language-detection dependency: at
    the length of a resume it is reliable, and it costs nothing to run.
    """
    words = _WORD_RE.findall(text.lower())
    if len(words) < 20:
        # Too little text to judge. Treated as English so that sparse resumes
        # are not rejected for the wrong reason.
        return 1.0
    return sum(1 for word in words if word in _ENGLISH_MARKERS) / len(words)


def _page_has_covering_image(page: mu.Page) -> bool:
    page_area = mu.area(page.rect)
    if page_area <= 0:
        return False
    for block in mu.text_dict(page)["blocks"]:
        if block.get("type") != 1:  # 1 = image
            continue
        if mu.area(mu.rect(block["bbox"])) / page_area >= _PAGE_COVER_RATIO:
            return True
    return False


def measure(doc: mu.Document) -> PdfStats:
    all_pages = mu.pages(doc)
    text = "".join(mu.plain_text(page) for page in all_pages)
    return PdfStats(
        page_count=doc.page_count,
        text_chars=len(text.strip()),
        image_count=sum(mu.image_count(page) for page in all_pages),
        has_page_covering_image=any(_page_has_covering_image(page) for page in all_pages),
        english_ratio=english_ratio(text),
    )


def _check_bytes(data: bytes, settings: Settings) -> None:
    if not data:
        raise RolevaError(ErrorCode.PDF_EMPTY)
    if len(data) > settings.max_upload_bytes:
        raise RolevaError(ErrorCode.FILE_TOO_LARGE)
    if not data.startswith(_PDF_MAGIC):
        raise RolevaError(ErrorCode.NOT_A_PDF)


def _check_document(doc: mu.Document, settings: Settings) -> PdfStats:
    if doc.needs_pass:
        raise RolevaError(ErrorCode.PDF_ENCRYPTED)
    if doc.page_count == 0:
        raise RolevaError(ErrorCode.PDF_EMPTY)
    if doc.page_count > settings.max_pages:
        raise RolevaError(
            ErrorCode.TOO_MANY_PAGES,
            f"This resume has {doc.page_count} pages. Please upload {settings.max_pages} or fewer.",
        )

    stats = measure(doc)

    # Scanned detection needs two signals. A sparse student resume can hold very
    # little text and is still perfectly valid, so text density alone would
    # reject real documents — it did, during development. What distinguishes a
    # scan is near-zero text *combined with* an image covering the page.
    if stats.chars_per_page < settings.min_chars_per_page:
        if stats.has_page_covering_image:
            raise RolevaError(ErrorCode.PDF_SCANNED)
        raise RolevaError(ErrorCode.PDF_EMPTY)

    if stats.english_ratio < 0.06:
        raise RolevaError(ErrorCode.UNSUPPORTED_LANGUAGE)

    return stats


@contextmanager
def open_validated(data: bytes, settings: Settings) -> Iterator[tuple[mu.Document, PdfStats]]:
    """Open an uploaded PDF, or raise a RolevaError explaining why not.

    The document is closed on exit whatever happens. Nothing is written to disk:
    the bytes exist only in memory and are discarded once parsing is done.
    """
    _check_bytes(data, settings)

    try:
        doc = mu.open_stream(data)
    except Exception as exc:  # any failure to open means the file is unreadable
        raise RolevaError(ErrorCode.PDF_CORRUPT) from exc

    try:
        stats = _check_document(doc, settings)
        yield doc, stats
    finally:
        mu.close(doc)


def filename_is_professional(filename: str | None) -> bool:
    """A small ATS signal, checked here because the filename is only available
    at upload time and is not part of the document."""
    if not filename:
        return True
    stem = filename.rsplit(".", 1)[0].lower()
    sloppy = ("final", "copy", "new", "updated", "untitled", "document", "asdf", "(1)", "v2")
    return not any(token in stem for token in sloppy)
