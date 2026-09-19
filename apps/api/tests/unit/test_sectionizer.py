"""Tests for section detection and contact extraction."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

from roleva.config import Settings
from roleva.models.resume import ContactInfo, SectionKind
from roleva.parsing.contact import (
    completeness,
    extract_contact,
    find_email,
    find_location,
    find_name,
    find_phone,
)
from roleva.parsing.normalizer import normalize
from roleva.parsing.pdf_reader import extract
from roleva.parsing.sectionizer import (
    HeadingSignals,
    SectionReport,
    classify_heading,
    score_line,
    sectionize,
)
from roleva.parsing.validators import open_validated


def analyse(resumes: Path, name: str) -> tuple[SectionReport, str]:
    with open_validated((resumes / name).read_bytes(), Settings()) as (doc, _):
        extracted = extract(doc)
    normalized = normalize(extracted.text)
    return sectionize(normalized, extracted), normalized.text


class TestHeadingClassification:
    @pytest.mark.parametrize(
        ("heading", "expected"),
        [
            ("Experience", SectionKind.EXPERIENCE),
            ("WORK EXPERIENCE", SectionKind.EXPERIENCE),
            ("Employment History", SectionKind.EXPERIENCE),
            ("Education", SectionKind.EDUCATION),
            ("Technical Skills", SectionKind.SKILLS),
            ("Projects", SectionKind.PROJECTS),
            ("Certifications", SectionKind.CERTIFICATIONS),
            ("Awards & Honors", SectionKind.AWARDS),
            ("Languages", SectionKind.LANGUAGES),
        ],
    )
    def test_conventional_headings_are_recognised(
        self, heading: str, expected: SectionKind
    ) -> None:
        assert classify_heading(heading)[0] is expected

    @pytest.mark.parametrize(
        ("heading", "expected"),
        [
            ("Where I've Worked", SectionKind.EXPERIENCE),
            ("Things I've Built", SectionKind.PROJECTS),
            ("My Toolkit", SectionKind.SKILLS),
            ("Academics", SectionKind.EDUCATION),
        ],
    )
    def test_informal_headings_are_recognised(self, heading: str, expected: SectionKind) -> None:
        assert classify_heading(heading)[0] is expected

    def test_punctuation_and_case_do_not_matter(self) -> None:
        assert classify_heading("— SKILLS —")[0] is SectionKind.SKILLS

    def test_the_longest_matching_phrase_wins(self) -> None:
        """ "Work experience" must not be shortened to "work"."""
        kind, exact = classify_heading("Work Experience")
        assert kind is SectionKind.EXPERIENCE
        assert exact is True

    def test_an_exact_match_is_marked_as_such(self) -> None:
        assert classify_heading("Skills")[1] is True
        assert classify_heading("Technical Skills and Tools")[1] is False

    def test_ordinary_prose_matches_nothing(self) -> None:
        assert classify_heading("Built a Django service handling 40,000 requests")[0] is None


class TestHeadingScoring:
    def test_signals_combine_into_a_score(self) -> None:
        signals = HeadingSignals(
            lexicon=True, larger_font=True, bold=True, short=True, all_caps=True
        )
        assert signals.is_heading is True

    def test_a_single_weak_signal_is_not_enough(self) -> None:
        assert HeadingSignals(short=True).is_heading is False

    def test_appearance_alone_can_identify_a_heading(self) -> None:
        """This is what lets an unconventional heading still be found."""
        signals = HeadingSignals(
            larger_font=True,
            bold=True,
            all_caps=True,
            short=True,
            no_terminal_punctuation=True,
        )
        assert signals.is_heading is True

    def test_wording_alone_is_not_quite_enough(self) -> None:
        """A sentence mentioning "experience" must not become a heading on that
        basis alone."""
        assert HeadingSignals(lexicon=True).is_heading is False


class TestSectionDetection:
    def test_a_conventional_resume_yields_its_sections(self, synthetic_resumes: Path) -> None:
        report, _ = analyse(synthetic_resumes, "single-column-classic.pdf")
        assert {
            SectionKind.EXPERIENCE,
            SectionKind.PROJECTS,
            SectionKind.EDUCATION,
            SectionKind.SKILLS,
        } <= report.kinds

    def test_the_contact_block_is_the_text_above_the_first_heading(
        self, synthetic_resumes: Path
    ) -> None:
        report, text = analyse(synthetic_resumes, "single-column-classic.pdf")
        contact = report.of_kind(SectionKind.CONTACT)
        assert contact is not None
        assert "Ananya" in contact.text(text)

    def test_creative_headings_are_still_classified(self, synthetic_resumes: Path) -> None:
        """The whole reason headings are scored rather than matched."""
        report, _ = analyse(synthetic_resumes, "creative-headings.pdf")
        assert SectionKind.EXPERIENCE in report.kinds
        assert SectionKind.PROJECTS in report.kinds

    def test_letter_spaced_headings_are_found_after_repair(self, synthetic_resumes: Path) -> None:
        report, _ = analyse(synthetic_resumes, "spaced-caps-headings.pdf")
        assert SectionKind.EXPERIENCE in report.kinds

    def test_a_fresher_with_no_experience_section_is_not_a_failure(
        self, synthetic_resumes: Path
    ) -> None:
        report, _ = analyse(synthetic_resumes, "projects-only-fresher.pdf")
        assert SectionKind.PROJECTS in report.kinds
        assert SectionKind.EXPERIENCE not in report.kinds

    def test_sections_do_not_overlap(self, synthetic_resumes: Path) -> None:
        report, _ = analyse(synthetic_resumes, "single-column-classic.pdf")
        ordered = sorted(report.sections, key=lambda s: s.start)
        for earlier, later in pairwise(ordered):
            assert earlier.end <= later.start

    def test_section_bodies_contain_their_content(self, synthetic_resumes: Path) -> None:
        report, text = analyse(synthetic_resumes, "single-column-classic.pdf")
        skills = report.of_kind(SectionKind.SKILLS)
        assert skills is not None
        assert "Python" in skills.text(text)

    def test_every_section_carries_a_confidence(self, synthetic_resumes: Path) -> None:
        report, _ = analyse(synthetic_resumes, "single-column-classic.pdf")
        assert all(0.0 <= section.confidence <= 1.0 for section in report.sections)

    @pytest.mark.parametrize(
        "name",
        [
            "single-column-classic.pdf",
            "two-column-sidebar.pdf",
            "creative-headings.pdf",
            "spaced-caps-headings.pdf",
            "projects-only-fresher.pdf",
            "table-layout.pdf",
            "sparse-minimal.pdf",
            "date-format-variety.pdf",
        ],
    )
    def test_the_corpus_always_yields_at_least_one_section(
        self, synthetic_resumes: Path, name: str
    ) -> None:
        report, _ = analyse(synthetic_resumes, name)
        assert report.sections


class TestContactName:
    def test_the_name_is_taken_from_the_top(self) -> None:
        assert find_name("Ananya Deshmukh\nsomeone@example.com") == "Ananya Deshmukh"

    def test_a_job_title_is_not_mistaken_for_a_name(self) -> None:
        assert find_name("Software Engineer\nBuilt things") is None

    def test_a_document_label_is_not_a_name(self) -> None:
        assert find_name("Curriculum Vitae\nAnanya Deshmukh") == "Ananya Deshmukh"

    def test_a_line_with_digits_is_not_a_name(self) -> None:
        assert find_name("Top 5 Achievements") is None

    def test_a_contact_line_is_not_a_name(self) -> None:
        assert find_name("ananya@example.com | +91 98220 41567") is None


class TestContactDetails:
    def test_an_email_is_found(self) -> None:
        assert find_email("reach me at a.b@example.co.in today") == "a.b@example.co.in"

    def test_a_phone_number_is_found(self) -> None:
        assert find_phone("Ananya\n+91 98220 41567") is not None

    def test_a_metric_is_not_read_as_a_phone_number(self) -> None:
        """The reason the pattern is conservative."""
        assert find_phone("Built a service handling 40000 requests per day") is None

    def test_a_year_range_is_not_read_as_a_phone_number(self) -> None:
        assert find_phone("Worked there 2022 2026 full time") is None

    def test_a_location_is_found(self) -> None:
        assert find_location("Ananya Deshmukh\nPune, Maharashtra") == "Pune, Maharashtra"

    def test_links_are_collected(self) -> None:
        links = find_links_helper("linkedin.com/in/ananya | github.com/ananya")
        assert len(links) == 2


def find_links_helper(text: str) -> list[str]:
    from roleva.parsing.contact import find_links

    return find_links(text)


class TestContactAgainstTheCorpus:
    def test_a_full_contact_block_is_extracted(self, synthetic_resumes: Path) -> None:
        _, text = analyse(synthetic_resumes, "single-column-classic.pdf")
        contact = extract_contact(text)
        assert contact.name == "Ananya Deshmukh"
        assert contact.email == "ananya.deshmukh@example.com"
        assert contact.phone is not None
        assert contact.links

    def test_contact_details_in_a_page_header_are_still_found(
        self, synthetic_resumes: Path
    ) -> None:
        _, text = analyse(synthetic_resumes, "contact-in-header-footer.pdf")
        contact = extract_contact(text)
        assert contact.email == "ananya.deshmukh@example.com"

    def test_a_sparse_resume_yields_what_it_has(self, synthetic_resumes: Path) -> None:
        _, text = analyse(synthetic_resumes, "sparse-minimal.pdf")
        contact = extract_contact(text)
        assert contact.email is not None
        assert contact.phone is None


class TestCompleteness:
    def test_a_full_block_scores_one(self) -> None:
        contact = ContactInfo(
            name="A B", email="a@b.com", phone="+91 98220 41567", links=["github.com/a"]
        )
        assert completeness(contact) == 1.0

    def test_an_empty_block_scores_zero(self) -> None:
        assert completeness(ContactInfo()) == 0.0

    def test_a_partial_block_scores_in_between(self) -> None:
        assert 0 < completeness(ContactInfo(name="A B", email="a@b.com")) < 1


class TestLabelledListsAreNotSections:
    """ "Languages: Python, JavaScript" belongs inside the skills section rather
    than opening one of its own."""

    def test_a_labelled_list_is_not_a_heading(self) -> None:
        signals = score_line(
            "Languages: Python, JavaScript, TypeScript",
            source=None,
            body_size=10.0,
            gap_before=True,
            content_after=True,
        )
        assert signals.is_heading is False

    def test_a_bare_label_is_still_a_heading(self) -> None:
        signals = score_line(
            "Skills:",
            source=None,
            body_size=10.0,
            gap_before=True,
            content_after=True,
        )
        assert signals.lexicon is True

    def test_the_sidebar_resume_has_one_skills_section(self, synthetic_resumes: Path) -> None:
        report, _ = analyse(synthetic_resumes, "two-column-sidebar.pdf")
        kinds = [section.kind for section in report.sections]
        assert kinds.count(SectionKind.SKILLS) == 1
