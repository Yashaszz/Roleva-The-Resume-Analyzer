"""Tests for the ATS rules and writing metrics.

Both are fully deterministic, so these are ordinary assertions about measured
facts — no model, no tolerance bands, no flakiness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from roleva.ats.rules import AtsContext, registered_rules, run
from roleva.ats.signals import collect
from roleva.config import Settings
from roleva.models.ats import AtsRuleId
from roleva.models.resume import (
    Bullet,
    ContactInfo,
    DateRange,
    ExperienceItem,
    ResumeDocument,
)
from roleva.parsing.contact import extract_contact
from roleva.parsing.normalizer import normalize
from roleva.parsing.pdf_reader import extract
from roleva.parsing.sectionizer import sectionize
from roleva.parsing.validators import open_validated
from roleva.quality.metrics import (
    has_number,
    measure,
    opens_with_action_verb,
    weak_phrases_in,
)


def analyse(resumes: Path, name: str, *, filename: str | None = None) -> AtsContext:
    with open_validated((resumes / name).read_bytes(), Settings()) as (doc, stats):
        extracted = extract(doc)
        signals = collect(doc)

    normalized = normalize(extracted.text)
    sections = sectionize(normalized, extracted)
    contact = extract_contact(normalized.text)

    return AtsContext(
        extracted=extracted,
        signals=signals,
        sections=sections,
        document=ResumeDocument(contact=contact, page_count=extracted.page_count),
        stats=stats,
        filename=filename,
    )


def rule_ids(resumes: Path, name: str, **kwargs: object) -> set[AtsRuleId]:
    report = run(analyse(resumes, name, **kwargs))  # type: ignore[arg-type]
    return {finding.rule_id for finding in report.findings}


class TestRegistry:
    def test_every_check_is_registered(self) -> None:
        assert len(registered_rules()) >= 14

    def test_the_report_records_how_many_ran(self, synthetic_resumes: Path) -> None:
        report = run(analyse(synthetic_resumes, "single-column-classic.pdf"))
        assert report.checks_run == len(registered_rules())


class TestLayoutChecks:
    def test_a_two_column_resume_is_flagged(self, synthetic_resumes: Path) -> None:
        assert AtsRuleId.MULTI_COLUMN in rule_ids(synthetic_resumes, "two-column-sidebar.pdf")

    def test_a_single_column_resume_is_not(self, synthetic_resumes: Path) -> None:
        assert AtsRuleId.MULTI_COLUMN not in rule_ids(
            synthetic_resumes, "single-column-classic.pdf"
        )

    def test_a_table_layout_is_flagged(self, synthetic_resumes: Path) -> None:
        assert AtsRuleId.TEXT_IN_TABLE in rule_ids(synthetic_resumes, "table-layout.pdf")

    def test_margin_content_is_flagged(self, synthetic_resumes: Path) -> None:
        """Contact details in a page header are a common reason applications go
        unanswered."""
        assert AtsRuleId.CONTENT_IN_HEADER_FOOTER in rule_ids(
            synthetic_resumes, "contact-in-header-footer.pdf"
        )

    def test_an_ordinary_resume_has_no_margin_content(self, synthetic_resumes: Path) -> None:
        assert AtsRuleId.CONTENT_IN_HEADER_FOOTER not in rule_ids(
            synthetic_resumes, "single-column-classic.pdf"
        )


class TestHiddenText:
    def test_hidden_text_is_the_most_severe_finding(self, synthetic_resumes: Path) -> None:
        report = run(analyse(synthetic_resumes, "hidden-white-text.pdf"))
        hidden = next(f for f in report.findings if f.rule_id is AtsRuleId.HIDDEN_TEXT)
        assert hidden.deduction == 20
        assert report.hidden_text_detected is True

    def test_the_finding_explains_the_real_risk(self, synthetic_resumes: Path) -> None:
        """Not "this is untidy" — employers discard applications over this."""
        report = run(analyse(synthetic_resumes, "hidden-white-text.pdf"))
        hidden = next(f for f in report.findings if f.rule_id is AtsRuleId.HIDDEN_TEXT)
        assert "discard" in hidden.detail

    def test_a_clean_resume_is_not_flagged(self, synthetic_resumes: Path) -> None:
        assert AtsRuleId.HIDDEN_TEXT not in rule_ids(synthetic_resumes, "single-column-classic.pdf")


class TestStructureChecks:
    def test_missing_sections_are_flagged(self, synthetic_resumes: Path) -> None:
        found = rule_ids(synthetic_resumes, "sparse-minimal.pdf")
        assert AtsRuleId.MISSING_EXPERIENCE in found

    def test_a_projects_section_satisfies_the_experience_check(
        self, synthetic_resumes: Path
    ) -> None:
        """A fresher with projects and no jobs has not failed."""
        assert AtsRuleId.MISSING_EXPERIENCE not in rule_ids(
            synthetic_resumes, "projects-only-fresher.pdf"
        )

    def test_a_complete_resume_passes_the_structure_checks(self, synthetic_resumes: Path) -> None:
        found = rule_ids(synthetic_resumes, "single-column-classic.pdf")
        assert AtsRuleId.NO_STANDARD_SECTIONS not in found
        assert AtsRuleId.MISSING_EDUCATION not in found


class TestContactChecks:
    def test_a_missing_email_is_critical(self, synthetic_resumes: Path) -> None:
        context = analyse(synthetic_resumes, "single-column-classic.pdf")
        context.document = ResumeDocument(contact=ContactInfo())
        report = run(context)
        finding = next(f for f in report.findings if f.rule_id is AtsRuleId.MISSING_EMAIL)
        assert finding.deduction == 10

    def test_a_present_email_is_not_flagged(self, synthetic_resumes: Path) -> None:
        assert AtsRuleId.MISSING_EMAIL not in rule_ids(
            synthetic_resumes, "single-column-classic.pdf"
        )


class TestFilenameCheck:
    def test_a_sloppy_filename_is_flagged(self, synthetic_resumes: Path) -> None:
        found = rule_ids(
            synthetic_resumes, "single-column-classic.pdf", filename="resume final.pdf"
        )
        assert AtsRuleId.UNPROFESSIONAL_FILENAME in found

    def test_a_clear_filename_is_not(self, synthetic_resumes: Path) -> None:
        found = rule_ids(
            synthetic_resumes,
            "single-column-classic.pdf",
            filename="Ananya_Deshmukh_Resume.pdf",
        )
        assert AtsRuleId.UNPROFESSIONAL_FILENAME not in found


class TestFindingQuality:
    """A deduction the user cannot act on is just a number that feels bad."""

    def test_every_finding_says_what_where_why_and_how(self, synthetic_resumes: Path) -> None:
        for name in ("two-column-sidebar.pdf", "table-layout.pdf", "hidden-white-text.pdf"):
            report = run(analyse(synthetic_resumes, name))
            for finding in report.findings:
                assert finding.title
                assert len(finding.detail) > 40
                assert len(finding.fix) > 15
                assert finding.deduction > 0

    def test_deductions_accumulate(self, synthetic_resumes: Path) -> None:
        report = run(analyse(synthetic_resumes, "two-column-sidebar.pdf"))
        assert report.total_deduction >= 15

    def test_results_are_identical_across_runs(self, synthetic_resumes: Path) -> None:
        """Determinism is the whole point of doing this without a model."""
        first = run(analyse(synthetic_resumes, "two-column-sidebar.pdf"))
        second = run(analyse(synthetic_resumes, "two-column-sidebar.pdf"))
        assert first.total_deduction == second.total_deduction
        assert [f.rule_id for f in first.findings] == [f.rule_id for f in second.findings]


class TestQuantification:
    @pytest.mark.parametrize(
        "text",
        [
            "Reduced latency by 40%",
            "Served 40,000 requests per day",
            "Saved $12,000 annually",
            "Mentored 3 interns",
            "Cut build time from 22 minutes to 4",
        ],
    )
    def test_measurable_results_are_recognised(self, text: str) -> None:
        assert has_number(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "Responsible for the deployment pipeline",
            "Worked on the customer dashboard",
            "Built a Django service",
        ],
    )
    def test_unquantified_bullets_are_recognised(self, text: str) -> None:
        assert has_number(text) is False

    def test_a_bare_year_does_not_count_as_a_result(self) -> None:
        """ "Worked there in 2024" quantifies nothing about what was achieved."""
        assert has_number("Joined the team in 2024") is False


class TestActionVerbs:
    @pytest.mark.parametrize(
        "text", ["Built a service", "Reduced latency", "• Migrated the database"]
    )
    def test_strong_openers_are_recognised(self, text: str) -> None:
        assert opens_with_action_verb(text) is True

    @pytest.mark.parametrize(
        "text", ["Responsible for testing", "Was involved in the migration", "Team player"]
    )
    def test_weak_openers_are_recognised(self, text: str) -> None:
        assert opens_with_action_verb(text) is False

    def test_a_bullet_marker_does_not_confuse_the_check(self) -> None:
        assert opens_with_action_verb("—  Designed the schema") is True


class TestWeakPhrases:
    def test_filler_is_detected(self) -> None:
        assert weak_phrases_in("Responsible for maintaining the site")

    def test_clean_writing_is_not_flagged(self) -> None:
        assert weak_phrases_in("Rebuilt the deployment pipeline") == []


class TestMetrics:
    def _document(self, bullets: list[str]) -> ResumeDocument:
        return ResumeDocument(
            experience=[
                ExperienceItem(
                    title="Engineer",
                    dates=DateRange(start_year=2024, end_year=2025),
                    bullets=[Bullet(text=text) for text in bullets],
                )
            ]
        )

    def test_a_well_written_resume_meets_its_targets(self) -> None:
        report = measure(
            self._document(
                [
                    "Built a Django service handling 40,000 requests per day",
                    "Reduced p95 latency from 820ms to 210ms by adding indexes",
                    "Wrote 60 unit tests, raising coverage from 34% to 81%",
                    "Mentored 2 interns through their first production deployment",
                ]
            )
        )
        assert report.get("quantification").meets_target  # type: ignore[union-attr]
        assert report.get("action_verbs").meets_target  # type: ignore[union-attr]
        assert report.get("weak_phrases").meets_target  # type: ignore[union-attr]

    def test_a_poorly_written_resume_fails_them(self) -> None:
        report = measure(
            self._document(
                [
                    "Responsible for the website",
                    "Worked on various tasks",
                    "Helped with testing",
                    "I was involved in the migration",
                ]
            )
        )
        failing = {metric.key for metric in report.failing}
        assert {"quantification", "action_verbs", "weak_phrases"} <= failing

    def test_failures_point_at_the_offending_bullets(self) -> None:
        """A low score has to name the lines that caused it."""
        report = measure(self._document(["Responsible for the website"]))
        weak = report.get("weak_phrases")
        assert weak is not None
        assert "Responsible for the website" in weak.offenders

    def test_first_person_is_counted(self) -> None:
        report = measure(self._document(["I built the service", "Built the API"]))
        assert report.get("first_person").value == 0.5  # type: ignore[union-attr]

    def test_repeated_openers_reduce_variety(self) -> None:
        report = measure(self._document(["Built A", "Built B", "Built C", "Built D", "Shipped E"]))
        assert report.get("opener_variety").value < 1.0  # type: ignore[union-attr]

    def test_attainment_is_comparable_across_metrics(self) -> None:
        report = measure(self._document(["Built a service handling 40,000 requests daily"]))
        for metric in report.metrics:
            assert 0.0 <= metric.attainment <= 1.0

    def test_a_resume_with_no_bullets_is_handled(self) -> None:
        report = measure(ResumeDocument())
        assert report.bullet_count == 0
        assert report.metrics == []

    def test_measurement_is_deterministic(self) -> None:
        document = self._document(["Built a service handling 40,000 requests daily"])
        first = measure(document)
        second = measure(document)
        assert [m.value for m in first.metrics] == [m.value for m in second.metrics]
