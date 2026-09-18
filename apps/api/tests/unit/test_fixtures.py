"""Guards on the fixture corpus itself.

A test suite is only as good as its fixtures, and these are easy to break by
accident — a file renamed, an expectation added for a file that no longer
exists, a JD edited until it no longer triggers the case it was written for.
These tests keep the corpus and its ground truth in agreement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from roleva.config import Settings
from roleva.models.job import Priority

JD_DIR = Path(__file__).parents[1] / "fixtures" / "jds"
MANIFEST = JD_DIR / "manifest.yaml"


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = manifest["fixtures"]
    return fixtures


class TestCorpusIntegrity:
    def test_every_manifest_entry_has_its_file(self, entries: list[dict[str, Any]]) -> None:
        missing = [e["file"] for e in entries if not (JD_DIR / e["file"]).is_file()]
        assert missing == []

    def test_every_file_is_described_in_the_manifest(self, entries: list[dict[str, Any]]) -> None:
        described = {e["file"] for e in entries}
        on_disk = {p.name for p in JD_DIR.glob("*.txt")}
        assert on_disk - described == set()

    def test_the_corpus_meets_its_minimum_size(self, entries: list[dict[str, Any]]) -> None:
        assert len(entries) >= 15

    def test_every_entry_explains_what_it_tests(self, entries: list[dict[str, Any]]) -> None:
        assert all(e.get("tests") for e in entries)


class TestCoverage:
    """The corpus must span the role families and levels Roleva targets."""

    def test_multiple_role_families_are_represented(self, entries: list[dict[str, Any]]) -> None:
        families = {e["role_family"] for e in entries if "role_family" in e}
        assert len(families) >= 6

    def test_both_intern_and_entry_levels_appear(self, entries: list[dict[str, Any]]) -> None:
        levels = {e["seniority"] for e in entries if "seniority" in e}
        assert {"intern", "entry"} <= levels

    def test_non_technical_roles_are_included(self, entries: list[dict[str, Any]]) -> None:
        families = {e.get("role_family") for e in entries}
        assert families & {"product_management", "design", "business_analysis"}


class TestPriorityExpectations:
    def test_expected_priorities_are_valid(self, entries: list[dict[str, Any]]) -> None:
        valid = {p.value for p in Priority}
        for entry in entries:
            for requirement in entry.get("must_include", []):
                assert requirement["priority"] in valid, entry["file"]

    def test_all_three_priority_tiers_are_exercised(self, entries: list[dict[str, Any]]) -> None:
        seen = {
            requirement["priority"]
            for entry in entries
            for requirement in entry.get("must_include", [])
        }
        assert seen == {p.value for p in Priority}

    def test_quantified_requirements_are_covered(self, entries: list[dict[str, Any]]) -> None:
        quantified = [
            requirement
            for entry in entries
            for requirement in entry.get("must_include", [])
            if "years" in requirement
        ]
        assert len(quantified) >= 2


class TestValidationCases:
    """The length thresholds must actually be triggered by the corpus."""

    def test_the_reject_case_is_below_the_floor(self, entries: list[dict[str, Any]]) -> None:
        settings = Settings()
        entry = next(e for e in entries if e.get("expect_error") == "jd_too_short")
        text = (JD_DIR / entry["file"]).read_text(encoding="utf-8")
        assert len(text) < settings.min_jd_chars

    def test_the_warning_case_sits_between_the_thresholds(
        self, entries: list[dict[str, Any]]
    ) -> None:
        settings = Settings()
        entry = next(e for e in entries if e.get("expect_warning"))
        text = (JD_DIR / entry["file"]).read_text(encoding="utf-8")
        assert settings.min_jd_chars <= len(text) < settings.warn_jd_chars

    def test_ordinary_fixtures_are_comfortably_above_the_warning_threshold(
        self, entries: list[dict[str, Any]]
    ) -> None:
        settings = Settings()
        for entry in entries:
            if entry.get("expect_error") or entry.get("expect_warning"):
                continue
            text = (JD_DIR / entry["file"]).read_text(encoding="utf-8")
            assert len(text) >= settings.warn_jd_chars, entry["file"]


class TestBoilerplateCase:
    """The cleaner has a dedicated fixture; it must really contain boilerplate."""

    def test_the_boilerplate_fixture_contains_what_should_be_stripped(
        self, entries: list[dict[str, Any]]
    ) -> None:
        entry = next(e for e in entries if e["file"] == "sde-entry-boilerplate.txt")
        text = (JD_DIR / entry["file"]).read_text(encoding="utf-8")
        for phrase in entry["must_not_include"]:
            assert phrase in text, f"{phrase} should be present so the cleaner can remove it"
