"""Tests for the upload validation gate.

Runs against the synthetic corpus, which contains a purpose-built fixture for
every rejection path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from roleva.api.errors import ErrorCode, RolevaError
from roleva.config import Settings
from roleva.parsing.validators import (
    english_ratio,
    filename_is_professional,
    open_validated,
)


def load(resumes: Path, name: str) -> bytes:
    return (resumes / name).read_bytes()


def validate(data: bytes, settings: Settings | None = None) -> ErrorCode | None:
    """Returns the rejection code, or None when the file is accepted."""
    try:
        with open_validated(data, settings or Settings()):
            return None
    except RolevaError as exc:
        return exc.code


class TestAcceptsValidResumes:
    @pytest.mark.parametrize(
        "name",
        [
            "single-column-classic.pdf",
            "two-column-sidebar.pdf",
            "table-layout.pdf",
            "contact-in-header-footer.pdf",
            "creative-headings.pdf",
            "spaced-caps-headings.pdf",
            "bullet-glyph-variety.pdf",
            "serif-with-ligatures.pdf",
            "date-format-variety.pdf",
            "projects-only-fresher.pdf",
            "sparse-minimal.pdf",
            "two-pages-dense.pdf",
            "hidden-white-text.pdf",
            "injection-attempt.pdf",
        ],
    )
    def test_a_real_resume_is_accepted(self, synthetic_resumes: Path, name: str) -> None:
        assert validate(load(synthetic_resumes, name)) is None

    def test_statistics_are_measured_on_the_way_through(self, synthetic_resumes: Path) -> None:
        with open_validated(load(synthetic_resumes, "two-pages-dense.pdf"), Settings()) as (
            doc,
            stats,
        ):
            assert doc.page_count == 2
            assert stats.page_count == 2
            assert stats.text_chars > 500
            assert stats.english_ratio > 0.1


class TestRejections:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("not-really-a-pdf.pdf", ErrorCode.NOT_A_PDF),
            ("encrypted.pdf", ErrorCode.PDF_ENCRYPTED),
            ("scanned-image.pdf", ErrorCode.PDF_SCANNED),
            ("empty-pages.pdf", ErrorCode.PDF_EMPTY),
            ("too-many-pages.pdf", ErrorCode.TOO_MANY_PAGES),
        ],
    )
    def test_each_invalid_fixture_is_rejected_for_the_right_reason(
        self, synthetic_resumes: Path, name: str, expected: ErrorCode
    ) -> None:
        assert validate(load(synthetic_resumes, name)) is expected

    def test_empty_upload_is_rejected(self) -> None:
        assert validate(b"") is ErrorCode.PDF_EMPTY

    def test_an_oversized_file_is_rejected_before_parsing(self) -> None:
        settings = Settings(max_upload_bytes=1024)
        assert validate(b"%PDF-" + b"x" * 5000, settings) is ErrorCode.FILE_TOO_LARGE

    def test_truncated_pdf_bytes_are_rejected_as_corrupt(self) -> None:
        assert validate(b"%PDF-1.7\nbroken") is ErrorCode.PDF_CORRUPT

    def test_the_page_cap_is_configurable(self, synthetic_resumes: Path) -> None:
        data = load(synthetic_resumes, "two-pages-dense.pdf")
        assert validate(data, Settings(max_pages=1)) is ErrorCode.TOO_MANY_PAGES
        assert validate(data, Settings(max_pages=2)) is None


class TestScannedDetectionNeedsTwoSignals:
    """A sparse resume and a scan are indistinguishable on text density alone.

    Rejecting sparse-minimal.pdf as a scan is a real failure that happened
    during development; this pair is the permanent guard against it.
    """

    def test_a_sparse_resume_is_accepted(self, synthetic_resumes: Path) -> None:
        assert validate(load(synthetic_resumes, "sparse-minimal.pdf")) is None

    def test_a_scan_is_rejected_as_scanned(self, synthetic_resumes: Path) -> None:
        assert validate(load(synthetic_resumes, "scanned-image.pdf")) is ErrorCode.PDF_SCANNED

    def test_a_textless_page_with_no_image_is_empty_not_scanned(
        self, synthetic_resumes: Path
    ) -> None:
        """Different cause, different message: 'export as text' would be
        useless advice for a genuinely blank document."""
        assert validate(load(synthetic_resumes, "empty-pages.pdf")) is ErrorCode.PDF_EMPTY

    def test_raising_the_text_floor_does_not_reclassify_a_sparse_resume(
        self, synthetic_resumes: Path
    ) -> None:
        """Even with an aggressive threshold, no page-covering image means it is
        reported as empty rather than as a scan."""
        settings = Settings(min_chars_per_page=5000)
        assert validate(load(synthetic_resumes, "sparse-minimal.pdf"), settings) is (
            ErrorCode.PDF_EMPTY
        )


class TestLanguageDetection:
    def test_english_resume_text_scores_high(self) -> None:
        text = (
            "Built a Django service and reduced latency. Worked with the team "
            "to design and develop the platform, using Python for the backend."
        )
        assert english_ratio(text) > 0.2

    def test_non_english_text_scores_low(self) -> None:
        text = (
            "Ingeniero de software con experiencia en desarrollo de aplicaciones "
            "web utilizando tecnologias modernas para empresas internacionales "
            "durante varios anos de trabajo profesional continuo"
        )
        assert english_ratio(text) < 0.06

    def test_very_short_text_is_not_judged(self) -> None:
        """Too few words to decide. A sparse resume must not be rejected as
        foreign-language when the real problem is that it is short."""
        assert english_ratio("Python Java SQL") == 1.0


class TestFilenameHeuristic:
    @pytest.mark.parametrize(
        "name", ["Ananya_Deshmukh_Resume.pdf", "resume.pdf", "ananya-cv-2026.pdf"]
    )
    def test_reasonable_filenames_pass(self, name: str) -> None:
        assert filename_is_professional(name) is True

    @pytest.mark.parametrize(
        "name",
        ["resume final.pdf", "Untitled document.pdf", "resume (1).pdf", "cv_new_v2.pdf"],
    )
    def test_sloppy_filenames_are_flagged(self, name: str) -> None:
        assert filename_is_professional(name) is False

    def test_a_missing_filename_is_not_penalised(self) -> None:
        assert filename_is_professional(None) is True
