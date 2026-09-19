"""Tests for offset-preserving normalisation.

Two things are being checked, and the second matters more:

  1. The text comes out clean.
  2. Every cleaned character still points at where it came from.

A normaliser that produces perfect text but loses the offsets would break the
product's core guarantee — that any claim can be traced to the exact characters
behind it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from roleva.config import Settings
from roleva.parsing.normalizer import NormalizedText, find_all, line_bounds, normalize
from roleva.parsing.pdf_reader import extract
from roleva.parsing.validators import open_validated


def normalized_resume(resumes: Path, name: str) -> NormalizedText:
    with open_validated((resumes / name).read_bytes(), Settings()) as (doc, _):
        return normalize(extract(doc).text)


class TestLigatures:
    """Ligatures arrive as single codepoints, so "Profiled" is not the string
    "Profiled" until they are expanded. Left alone, every keyword match fails."""

    def test_common_ligatures_are_expanded(self) -> None:
        result = normalize("Proﬁled and reﬁned the workﬂow")
        assert result.text == "Profiled and refined the workflow"

    def test_the_expansion_still_points_at_its_source(self) -> None:
        result = normalize("Proﬁled")
        # "fi" came from one original character, so both map back to it.
        start, end = result.original_span(3, 5)
        assert result.original[start:end] == "ﬁ"

    def test_a_word_containing_a_ligature_is_locatable(self) -> None:
        result = normalize("Built and reﬁned the pipeline")
        at = result.text.index("refined")
        assert "refin" in result.verify(at, at + len("refined")) or result.verify(
            at, at + len("refined")
        ).startswith("re")


class TestBullets:
    def test_every_glyph_becomes_one_marker(self) -> None:
        result = normalize("• first\n▪ second\n– third\n◦ fourth\n* fifth")
        assert result.text.count("•") == 5

    def test_a_dash_inside_a_sentence_is_left_alone(self) -> None:
        """Position is what makes a dash a bullet. Rewriting mid-sentence
        punctuation would corrupt the text."""
        result = normalize("Built a well-tested service - fast and reliable")
        assert "•" not in result.text
        assert "well-tested" in result.text

    def test_an_indented_bullet_is_still_recognised(self) -> None:
        result = normalize("   ▪ indented item")
        assert "•" in result.text


class TestHyphenation:
    def test_a_line_wrapped_word_is_rejoined(self) -> None:
        result = normalize("Implemented auto-\nmation for the team")
        assert "automation" in result.text

    def test_a_genuine_compound_survives(self) -> None:
        result = normalize("Built a well-tested service")
        assert "well-tested" in result.text

    def test_a_hyphen_before_a_capital_is_not_joined(self) -> None:
        """A line ending in a hyphen before a capitalised word is far more
        likely to be a compound than a wrap."""
        result = normalize("React-\nNative developer")
        assert "ReactNative" not in result.text


class TestWhitespace:
    def test_repeated_spaces_collapse(self) -> None:
        assert normalize("Python     and      SQL").text == "Python and SQL"

    def test_trailing_spaces_are_trimmed_per_line(self) -> None:
        assert normalize("first   \nsecond  ").text == "first\nsecond"

    def test_blank_lines_are_preserved(self) -> None:
        """Vertical gaps are a signal the section detector uses."""
        assert "\n\n" in normalize("Experience\n\nSoftware Engineer").text


class TestSpacedCapsHeadings:
    def test_a_letter_spaced_heading_is_closed_up(self) -> None:
        result = normalize("E X P E R I E N C E\nSoftware Engineer")
        assert "EXPERIENCE" in result.text

    def test_the_repair_is_counted(self) -> None:
        result = normalize("E X P E R I E N C E\nbody\nS K I L L S")
        assert result.repaired_spaced_lines == 2

    def test_an_ordinary_sentence_is_untouched(self) -> None:
        text = "I led a team of five engineers"
        assert normalize(text).text == text

    def test_a_normal_heading_is_untouched(self) -> None:
        assert normalize("EXPERIENCE\nbody").text == "EXPERIENCE\nbody"


class TestOffsetFidelity:
    """The property the whole module exists to preserve."""

    def test_plain_text_maps_one_to_one(self) -> None:
        result = normalize("Built a Django service")
        at = result.text.index("Django")
        assert result.verify(at, at + 6) == "Django"

    def test_offsets_survive_whitespace_collapse(self) -> None:
        result = normalize("Python     and     SQL")
        at = result.text.index("SQL")
        assert result.verify(at, at + 3) == "SQL"

    def test_offsets_survive_bullet_replacement(self) -> None:
        result = normalize("▪ Built a Django service")
        at = result.text.index("Django")
        assert result.verify(at, at + 6) == "Django"

    def test_offsets_survive_hyphen_rejoining(self) -> None:
        result = normalize("Implemented auto-\nmation tooling")
        at = result.text.index("tooling")
        assert result.verify(at, at + 7) == "tooling"

    def test_offsets_survive_a_heading_repair(self) -> None:
        result = normalize("E X P E R I E N C E\nBuilt a Django service")
        at = result.text.index("Django")
        assert result.verify(at, at + 6) == "Django"

    def test_offsets_survive_every_transformation_at_once(self) -> None:
        raw = "S K I L L S\n▪  Proﬁled   auto-\nmation   workﬂows"
        result = normalize(raw)
        at = result.text.index("workflows")
        recovered = result.verify(at, at + len("workflows"))
        assert "work" in recovered

    def test_an_offset_past_the_end_does_not_explode(self) -> None:
        result = normalize("short")
        assert result.original_span(0, 9999)[1] <= len(result.original)

    def test_empty_input_is_handled(self) -> None:
        result = normalize("")
        assert result.text == ""
        assert result.original_span(0, 0) == (0, 0)


class TestAgainstTheRealCorpus:
    @pytest.mark.parametrize(
        "name",
        [
            "single-column-classic.pdf",
            "two-column-sidebar.pdf",
            "serif-with-ligatures.pdf",
            "bullet-glyph-variety.pdf",
            "spaced-caps-headings.pdf",
            "table-layout.pdf",
            "sparse-minimal.pdf",
        ],
    )
    def test_every_word_can_be_traced_back(self, synthetic_resumes: Path, name: str) -> None:
        """For each distinctive word in the normalised text, the original range
        it maps to must contain a recognisable part of that word."""
        result = normalized_resume(synthetic_resumes, name)
        for word in ("Django", "Python", "Technology", "Skills", "React"):
            for start, end in find_all(result.text, word)[:3]:
                recovered = result.verify(start, end)
                assert word[:4].lower() in recovered.lower()

    def test_the_ligature_fixture_becomes_matchable(self, synthetic_resumes: Path) -> None:
        """Before normalisation these words contain ligature codepoints and
        match nothing."""
        result = normalized_resume(synthetic_resumes, "serif-with-ligatures.pdf")
        for word in ("Profiled", "Refined", "Identified", "classification"):
            assert word in result.text

    def test_the_bullet_fixture_ends_with_one_marker(self, synthetic_resumes: Path) -> None:
        result = normalized_resume(synthetic_resumes, "bullet-glyph-variety.pdf")
        for glyph in "▪◦":
            assert glyph not in result.text

    def test_the_spaced_heading_fixture_is_repaired(self, synthetic_resumes: Path) -> None:
        result = normalized_resume(synthetic_resumes, "spaced-caps-headings.pdf")
        assert result.repaired_spaced_lines > 0
        assert "EXPERIENCE" in result.text.upper()

    def test_normalisation_is_deterministic(self, synthetic_resumes: Path) -> None:
        first = normalized_resume(synthetic_resumes, "single-column-classic.pdf")
        second = normalized_resume(synthetic_resumes, "single-column-classic.pdf")
        assert first.text == second.text
        assert first.offsets.sources == second.offsets.sources


class TestHelpers:
    def test_find_all_locates_every_occurrence(self) -> None:
        assert find_all("a b a b a", "a") == [(0, 1), (4, 5), (8, 9)]

    def test_find_all_of_nothing_is_empty(self) -> None:
        assert find_all("anything", "") == []

    def test_line_bounds_returns_the_containing_line(self) -> None:
        text = "first line\nsecond line\nthird"
        start, end = line_bounds(text, 14)
        assert text[start:end] == "second line"

    def test_line_bounds_handles_the_final_line(self) -> None:
        text = "first\nlast"
        start, end = line_bounds(text, 7)
        assert text[start:end] == "last"
