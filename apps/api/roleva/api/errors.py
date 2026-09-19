"""Error taxonomy.

Error copy is UX, not a stack trace. Every failure the user can cause has a
specific code and a message that tells them how to fix it. Raw exceptions never
reach the client.
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import HTTPException, status


class ErrorCode(StrEnum):
    NOT_A_PDF = "not_a_pdf"
    FILE_TOO_LARGE = "file_too_large"
    TOO_MANY_PAGES = "too_many_pages"
    PDF_ENCRYPTED = "pdf_encrypted"
    PDF_CORRUPT = "pdf_corrupt"
    PDF_SCANNED = "pdf_scanned"
    PDF_EMPTY = "pdf_empty"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    JD_TOO_SHORT = "jd_too_short"
    QUOTA_EXCEEDED = "quota_exceeded"
    CAPACITY_REACHED = "capacity_reached"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"
    ANALYSIS_FAILED = "analysis_failed"
    UPSTREAM_TIMEOUT = "upstream_timeout"


#: Message shown to the user, and the HTTP status to return.
MESSAGES: dict[ErrorCode, tuple[int, str]] = {
    ErrorCode.NOT_A_PDF: (
        status.HTTP_400_BAD_REQUEST,
        "This doesn't look like a PDF file. Please upload a .pdf resume.",
    ),
    ErrorCode.FILE_TOO_LARGE: (
        status.HTTP_413_CONTENT_TOO_LARGE,
        "Your file is larger than 8 MB. Try exporting a smaller version.",
    ),
    ErrorCode.TOO_MANY_PAGES: (
        status.HTTP_400_BAD_REQUEST,
        "This resume has more than 10 pages. Please upload a shorter version.",
    ),
    ErrorCode.PDF_ENCRYPTED: (
        status.HTTP_400_BAD_REQUEST,
        "This PDF is password-protected. Please upload an unlocked copy.",
    ),
    ErrorCode.PDF_CORRUPT: (
        status.HTTP_400_BAD_REQUEST,
        "We couldn't open this PDF — it may be damaged. Try re-exporting it.",
    ),
    ErrorCode.PDF_SCANNED: (
        status.HTTP_400_BAD_REQUEST,
        "This looks like a scanned image rather than a text PDF. Export directly "
        "from Word, Google Docs, or Canva instead of scanning a printout.",
    ),
    ErrorCode.PDF_EMPTY: (
        status.HTTP_400_BAD_REQUEST,
        "We couldn't find any text in this PDF. Please check the file and try again.",
    ),
    ErrorCode.UNSUPPORTED_LANGUAGE: (
        status.HTTP_400_BAD_REQUEST,
        "Roleva currently supports English resumes only.",
    ),
    ErrorCode.JD_TOO_SHORT: (
        status.HTTP_400_BAD_REQUEST,
        "That job description is too short to analyze. Paste the full posting, "
        "including the requirements and responsibilities.",
    ),
    ErrorCode.QUOTA_EXCEEDED: (
        status.HTTP_429_TOO_MANY_REQUESTS,
        "You've used all your analyses for today. Your quota resets at midnight.",
    ),
    ErrorCode.CAPACITY_REACHED: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Roleva has reached today's analysis capacity. Please try again tomorrow.",
    ),
    ErrorCode.RATE_LIMITED: (
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many requests. Please wait a moment and try again.",
    ),
    ErrorCode.UNAUTHORIZED: (
        status.HTTP_401_UNAUTHORIZED,
        "Please sign in to continue.",
    ),
    ErrorCode.NOT_FOUND: (
        status.HTTP_404_NOT_FOUND,
        "We couldn't find that analysis.",
    ),
    ErrorCode.ANALYSIS_FAILED: (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Something went wrong while analyzing your resume. Please try again.",
    ),
    ErrorCode.UPSTREAM_TIMEOUT: (
        status.HTTP_504_GATEWAY_TIMEOUT,
        "The analysis took too long to complete. Please try again.",
    ),
}


class RolevaError(Exception):
    """Domain error carrying a user-facing code."""

    def __init__(self, code: ErrorCode, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code.value)

    @property
    def message(self) -> str:
        """The sentence shown to the user.

        Available without building an HTTPException, because a failure inside an
        already-open SSE stream has to be written into the stream rather than
        raised as a status code.
        """
        return self.detail or MESSAGES[self.code][1]

    def to_http(self) -> HTTPException:
        http_status, message = MESSAGES[self.code]
        return HTTPException(
            status_code=http_status,
            detail={"code": self.code.value, "message": self.detail or message},
        )
