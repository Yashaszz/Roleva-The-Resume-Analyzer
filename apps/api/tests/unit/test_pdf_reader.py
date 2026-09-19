"""Tests for PDF extraction, column detection and offset tracking.

The most important assertions here are about *reading order*. A parser that
extracts every word but interleaves two columns is worse than useless: it
produces confident, wrong output that every later stage inherits.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from roleva.config import Settings
from roleva.parsing.pdf_reader import ExtractedDocument, extract
from roleva.parsing.validators import open_validated


def read(resumes: Path, name: str) -> ExtractedDocument:
    data = (resumes / name).read_bytes()
    with open_validated(data, Settings()) as (doc, _):
        return extract(doc)


class TestBasicExtraction:
    def test_a_classic_resume_yields_its_content(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "single-column-classic.pdf")
        for expected in ("Django", "Zentara Technologies", "Pune Institute of Technology"):
            assert expected in result.text

    def test_lines_are_captured_with_positions(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "single-column-classic.pdf")
        assert len(result.lines) > 10
        assert all(line.page == 1 for line in result.lines)

    def test_page_count_is_reported(self, synthetic_resumes: Path) -> None:
        assert read(synthetic_resumes, "two-pages-dense.pdf").page_count == 2


class TestOffsets:
    """Every claim Roleva makes is anchored to a character range, so the offsets
    recorded here have to be exact."""

    def test_every_line_maps_to_its_own_text(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "single-column-classic.pdf")
        for line in result.lines:
            assert result.text[line.start : line.end] == line.text

    def test_offsets_are_exact_across_multiple_pages(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "two-pages-dense.pdf")
        for line in result.lines:
            assert result.text[line.start : line.end] == line.text

    def test_offsets_survive_a_two_column_layout(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "two-column-sidebar.pdf")
        for line in result.lines:
            assert result.text[line.start : line.end] == line.text

    def test_a_line_can_be_found_from_an_offset(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "single-column-classic.pdf")
        target = next(line for line in result.lines if "Django" in line.text)
        assert result.line_at(target.start) is target


class TestColumnDetection:
    def test_a_sidebar_layout_is_detected_as_multi_column(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "two-column-sidebar.pdf")
        assert result.multi_column_pages == [1]

    def test_a_single_column_resume_is_not_flagged(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "single-column-classic.pdf")
        assert result.multi_column_pages == []

    @pytest.mark.parametrize(
        "name",
        ["creative-headings.pdf", "projects-only-fresher.pdf", "date-format-variety.pdf"],
    )
    def test_indented_content_is_not_mistaken_for_a_column(
        self, synthetic_resumes: Path, name: str
    ) -> None:
        """Bullet indentation creates x-position clusters. Only a full-height
        gutter is a column."""
        assert read(synthetic_resumes, name).multi_column_pages == []


class TestReadingOrder:
    """The failure this whole module exists to prevent."""

    def test_the_sidebar_is_not_interleaved_with_the_main_column(
        self, synthetic_resumes: Path
    ) -> None:
        """The sidebar holds skills and education; the main column holds
        experience and projects. Each must appear as one contiguous run.

        Sorting purely by vertical position would produce something like
        "Skills / Experience / Languages: Python / Software Engineering Intern",
        which reads as nonsense and poisons every downstream stage.
        """
        text = read(synthetic_resumes, "two-column-sidebar.pdf").text

        sidebar_last = max(text.index("Languages:"), text.index("CGPA"))
        main_first = min(text.index("Zentara Technologies"), text.index("Experience"))

        # Everything from the sidebar precedes everything from the main column.
        assert sidebar_last < main_first

    def test_no_main_column_content_appears_inside_the_sidebar_run(
        self, synthetic_resumes: Path
    ) -> None:
        text = read(synthetic_resumes, "two-column-sidebar.pdf").text
        sidebar_run = text[: text.index("Zentara Technologies")]
        for main_only in ("Transit Delay Predictor", "Reduced p95", "Kalpa Studio"):
            assert main_only not in sidebar_run

    def test_each_column_reads_top_to_bottom(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "two-column-sidebar.pdf")
        for column in {line.column for line in result.lines}:
            in_column = [line for line in result.lines if line.column == column]
            tops = [line.bbox[1] for line in in_column]
            assert tops == sorted(tops)

    def test_columns_are_emitted_left_to_right(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "two-column-sidebar.pdf")
        columns = [line.column for line in result.lines]
        assert columns == sorted(columns)

    def test_pages_are_emitted_in_order(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "two-pages-dense.pdf")
        pages = [line.page for line in result.lines]
        assert pages == sorted(pages)


class TestHiddenText:
    def test_white_on_white_text_is_separated_out(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "hidden-white-text.pdf")
        assert result.hidden_lines
        assert any("Kubernetes" in line.text for line in result.hidden_lines)

    def test_hidden_text_never_reaches_the_document_body(self, synthetic_resumes: Path) -> None:
        """This is the guarantee that matters: stuffed keywords cannot be sent
        to a model or counted as evidence."""
        result = read(synthetic_resumes, "hidden-white-text.pdf")
        for stuffed in ("Kubernetes", "Terraform", "Scala"):
            assert stuffed not in result.text

    def test_visible_content_is_unaffected(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "hidden-white-text.pdf")
        assert "Django" in result.text
        assert "Zentara Technologies" in result.text

    def test_a_tiny_font_counts_as_hidden(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "injection-attempt.pdf")
        assert result.hidden_lines

    def test_an_ordinary_resume_has_no_hidden_text(self, synthetic_resumes: Path) -> None:
        assert read(synthetic_resumes, "single-column-classic.pdf").hidden_lines == []


class TestTypography:
    def test_body_size_is_measured_from_the_document(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "single-column-classic.pdf")
        assert 6 < result.body_size < 14

    def test_headings_are_larger_than_body_text(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "single-column-classic.pdf")
        heading = next(line for line in result.lines if "EXPERIENCE" in line.text.upper())
        assert heading.max_size > result.body_size

    def test_bold_runs_are_identified(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "single-column-classic.pdf")
        assert any(line.is_bold for line in result.lines)


class TestRepeatedHeaders:
    def test_a_repeating_page_header_is_stripped(self, synthetic_resumes: Path) -> None:
        result = read(synthetic_resumes, "two-pages-dense.pdf")
        assert result.repeated_lines
        assert result.text.count("Resume") <= 1

    def test_a_single_page_document_loses_nothing(self, synthetic_resumes: Path) -> None:
        assert read(synthetic_resumes, "single-column-classic.pdf").repeated_lines == []


class TestRobustness:
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
    def test_the_whole_corpus_extracts_with_consistent_offsets(
        self, synthetic_resumes: Path, name: str
    ) -> None:
        result = read(synthetic_resumes, name)
        assert result.text.strip()
        for line in result.lines:
            assert result.text[line.start : line.end] == line.text

    def test_extraction_is_deterministic(self, synthetic_resumes: Path) -> None:
        """Same bytes, same text — the foundation of reproducible scores."""
        first = read(synthetic_resumes, "two-column-sidebar.pdf")
        second = read(synthetic_resumes, "two-column-sidebar.pdf")
        assert first.text == second.text

    def test_a_page_with_no_text_is_handled(self) -> None:
        doc = pymupdf.open()
        doc.new_page(width=595, height=842)
        result = extract(doc)
        doc.close()
        assert result.text == ""
        assert result.lines == []
