"""Guards on the synthetic resume corpus.

These assert that each fixture genuinely exhibits the property it was written to
test. A fixture that quietly stops being adversarial is worse than no fixture,
because the suite still reports green.

They deliberately do not test the parser — that arrives in Phase 1. They test
that the corpus is fit to test the parser with.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf
import pytest
import yaml

from roleva.config import Settings

WHITE = 0xFFFFFF


@pytest.fixture(scope="module")
def entries(synthetic_resumes: Path) -> list[dict[str, Any]]:
    manifest = yaml.safe_load((synthetic_resumes / "manifest.yaml").read_text(encoding="utf-8"))
    fixtures: list[dict[str, Any]] = manifest["fixtures"]
    return fixtures


def text_of(path: Path) -> str:
    with pymupdf.open(path) as doc:
        return "".join(page.get_text() for page in doc)


class TestCorpusIntegrity:
    def test_every_manifest_entry_has_its_file(
        self, entries: list[dict[str, Any]], synthetic_resumes: Path
    ) -> None:
        missing = [e["file"] for e in entries if not (synthetic_resumes / e["file"]).is_file()]
        assert missing == []

    def test_every_generated_file_is_described(
        self, entries: list[dict[str, Any]], synthetic_resumes: Path
    ) -> None:
        described = {e["file"] for e in entries}
        on_disk = {p.name for p in synthetic_resumes.glob("*.pdf")}
        assert on_disk - described == set()

    def test_every_entry_explains_what_it_tests(self, entries: list[dict[str, Any]]) -> None:
        assert all(e.get("tests") for e in entries)

    def test_the_corpus_covers_valid_adversarial_and_invalid_cases(
        self, entries: list[dict[str, Any]]
    ) -> None:
        assert sum(1 for e in entries if e.get("expect") == "parse_ok") >= 12
        assert sum(1 for e in entries if e.get("expect_error")) >= 5


class TestInvalidCasesReallyAreInvalid:
    """Each rejection fixture must trigger its rejection for the stated reason."""

    def test_the_not_a_pdf_fixture_lacks_the_magic_bytes(self, synthetic_resumes: Path) -> None:
        data = (synthetic_resumes / "not-really-a-pdf.pdf").read_bytes()
        assert not data.startswith(b"%PDF-")

    def test_the_encrypted_fixture_needs_a_password(self, synthetic_resumes: Path) -> None:
        with pymupdf.open(synthetic_resumes / "encrypted.pdf") as doc:
            assert doc.needs_pass  # PyMuPDF returns an int, not a bool

    def test_the_scanned_fixture_has_an_image_and_no_text(self, synthetic_resumes: Path) -> None:
        with pymupdf.open(synthetic_resumes / "scanned-image.pdf") as doc:
            page = doc[0]
            assert page.get_text().strip() == ""
            assert len(page.get_images()) == 1

    def test_the_empty_fixture_has_neither_text_nor_images(self, synthetic_resumes: Path) -> None:
        with pymupdf.open(synthetic_resumes / "empty-pages.pdf") as doc:
            page = doc[0]
            assert page.get_text().strip() == ""
            assert len(page.get_images()) == 0

    def test_the_long_fixture_exceeds_the_page_cap(self, synthetic_resumes: Path) -> None:
        settings = Settings()
        with pymupdf.open(synthetic_resumes / "too-many-pages.pdf") as doc:
            assert doc.page_count > settings.max_pages


class TestScannedDetectionIsNotJustTextDensity:
    """A sparse but genuine resume must not be mistaken for a scan.

    This pair is the regression guard: an earlier 200-chars-per-page threshold
    rejected sparse-minimal.pdf, a perfectly valid student resume.
    """

    def test_a_sparse_resume_has_real_text_and_no_image(self, synthetic_resumes: Path) -> None:
        with pymupdf.open(synthetic_resumes / "sparse-minimal.pdf") as doc:
            page = doc[0]
            assert len(page.get_text().strip()) > 100
            assert len(page.get_images()) == 0

    def test_the_sparse_resume_clears_the_text_floor(self, synthetic_resumes: Path) -> None:
        settings = Settings()
        with pymupdf.open(synthetic_resumes / "sparse-minimal.pdf") as doc:
            chars = len(doc[0].get_text())
            assert chars > settings.min_chars_per_page

    def test_a_scan_falls_below_the_text_floor(self, synthetic_resumes: Path) -> None:
        settings = Settings()
        with pymupdf.open(synthetic_resumes / "scanned-image.pdf") as doc:
            assert len(doc[0].get_text()) < settings.min_chars_per_page


class TestAdversarialCases:
    def test_the_hidden_text_fixture_contains_white_on_white_spans(
        self, synthetic_resumes: Path
    ) -> None:
        with pymupdf.open(synthetic_resumes / "hidden-white-text.pdf") as doc:
            white = [
                span["text"]
                for page in doc
                for block in page.get_text("dict")["blocks"]
                for line in block.get("lines", [])
                for span in line["spans"]
                if span["color"] == WHITE
            ]
        assert white
        assert any("Kubernetes" in text for text in white)

    def test_the_hidden_keywords_are_not_in_the_visible_content(
        self, synthetic_resumes: Path
    ) -> None:
        """They must be extractable — that is how we detect them — but they are
        stuffing, not evidence, and must never count toward a match."""
        with pymupdf.open(synthetic_resumes / "hidden-white-text.pdf") as doc:
            visible = [
                span["text"]
                for page in doc
                for block in page.get_text("dict")["blocks"]
                for line in block.get("lines", [])
                for span in line["spans"]
                if span["color"] != WHITE
            ]
        assert not any("Terraform" in text for text in visible)

    def test_the_injection_fixture_carries_an_instruction_phrase(
        self, synthetic_resumes: Path
    ) -> None:
        from roleva.llm.sanitize import find_injection_markers

        assert find_injection_markers(text_of(synthetic_resumes / "injection-attempt.pdf"))

    def test_an_ordinary_resume_carries_no_injection_markers(self, synthetic_resumes: Path) -> None:
        from roleva.llm.sanitize import find_injection_markers

        assert (
            find_injection_markers(text_of(synthetic_resumes / "single-column-classic.pdf")) == []
        )


class TestStructuralCases:
    def test_the_ligature_fixture_extracts_words_containing_fi_and_fl(
        self, synthetic_resumes: Path
    ) -> None:
        """Whether these arrive as ligature codepoints or plain ASCII depends on
        the font. Either way the normaliser must leave the words matchable."""
        text = text_of(synthetic_resumes / "serif-with-ligatures.pdf")
        for word in ("Pro", "Re", "Identi"):
            assert word in text

    def test_the_bullet_fixture_uses_several_distinct_glyphs(self, synthetic_resumes: Path) -> None:
        text = text_of(synthetic_resumes / "bullet-glyph-variety.pdf")
        glyphs = {glyph for glyph in "•▪–◦*" if glyph in text}
        assert len(glyphs) >= 4

    def test_the_two_column_fixture_has_text_in_two_x_bands(self, synthetic_resumes: Path) -> None:
        """If blocks did not separate into two horizontal bands, the fixture
        would not actually be testing column handling."""
        with pymupdf.open(synthetic_resumes / "two-column-sidebar.pdf") as doc:
            lefts = [block[0] for block in doc[0].get_text("blocks")]
        assert min(lefts) < 220
        assert max(lefts) > 220

    def test_the_two_page_fixture_repeats_its_header(self, synthetic_resumes: Path) -> None:
        with pymupdf.open(synthetic_resumes / "two-pages-dense.pdf") as doc:
            assert doc.page_count == 2
            assert all("Resume" in page.get_text() for page in doc)

    def test_the_spaced_caps_fixture_really_is_letter_spaced(self, synthetic_resumes: Path) -> None:
        text = text_of(synthetic_resumes / "spaced-caps-headings.pdf")
        assert "EXPERIENCE" not in text.replace(" ", "X")
