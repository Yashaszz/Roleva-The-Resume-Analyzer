"""Tests for span verification, structuring and parse confidence.

The theme is the same throughout: a model may only report what is actually in
the resume. Anything else is dropped before it can be shown to anyone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from roleva.config import Settings
from roleva.models.common import SourceDoc
from roleva.models.resume import ResumeDocument, SkillOrigin
from roleva.parsing.confidence import (
    HIGH_CONFIDENCE,
    LOW_CONFIDENCE,
    ConfidenceBreakdown,
    assess,
    explain,
)
from roleva.parsing.contact import extract_contact
from roleva.parsing.normalizer import NormalizedText, normalize
from roleva.parsing.pdf_reader import ExtractedDocument, extract
from roleva.parsing.sectionizer import SectionReport, sectionize
from roleva.parsing.spans import locate, locate_many, verify_all
from roleva.parsing.structurer import (
    LlmEducation,
    LlmExperience,
    LlmProject,
    LlmResume,
    build_prompt,
    to_document,
)
from roleva.parsing.validators import open_validated

RESUME = """Ananya Deshmukh
ananya.deshmukh@example.com | +91 98220 41567

Experience
Software Engineering Intern - Zentara Technologies
June 2025 - August 2025
• Built a Django REST service handling 40,000 requests per day
• Reduced p95 API latency from 820ms to 210ms

Skills
Languages: Python, JavaScript, SQL
"""


def parsed(resumes: Path, name: str) -> tuple[ExtractedDocument, NormalizedText, SectionReport]:
    with open_validated((resumes / name).read_bytes(), Settings()) as (doc, _):
        extracted = extract(doc)
    normalized = normalize(extracted.text)
    sections = sectionize(normalized, extracted)
    return extracted, normalized, sections


class TestLocating:
    def test_an_exact_quote_is_located(self) -> None:
        span = locate(RESUME, "Built a Django REST service handling 40,000 requests per day")
        assert span is not None
        assert span.verify(RESUME)

    def test_a_bullet_marker_is_tolerated(self) -> None:
        span = locate(RESUME, "• Reduced p95 API latency from 820ms to 210ms")
        assert span is not None
        assert span.verify(RESUME)

    def test_differing_whitespace_is_tolerated(self) -> None:
        """A model retyping a bullet rarely reproduces PDF spacing exactly."""
        span = locate(RESUME, "Built  a   Django  REST service handling 40,000 requests per day")
        assert span is not None
        assert span.verify(RESUME)

    def test_trailing_punctuation_is_tolerated(self) -> None:
        span = locate(RESUME, "Reduced p95 API latency from 820ms to 210ms.")
        assert span is not None

    def test_invented_text_is_not_located(self) -> None:
        """The anti-hallucination guarantee, stated as a test."""
        assert locate(RESUME, "Led a team of twelve engineers at Google") is None

    def test_a_plausible_embellishment_is_not_located(self) -> None:
        assert locate(RESUME, "Built a Django REST service handling 400,000 requests") is None

    def test_an_empty_needle_finds_nothing(self) -> None:
        assert locate(RESUME, "") is None

    def test_the_located_span_carries_the_real_text(self) -> None:
        span = locate(RESUME, "Python")
        assert span is not None
        assert RESUME[span.start : span.end] == span.text


class TestBulkLocating:
    def test_found_and_missing_are_separated(self) -> None:
        found, missing = locate_many(
            RESUME,
            ["Python", "JavaScript", "Kubernetes", "Terraform"],
        )
        assert {text for text, _ in found} == {"Python", "JavaScript"}
        assert set(missing) == {"Kubernetes", "Terraform"}

    def test_verify_all_splits_by_validity(self) -> None:
        good = locate(RESUME, "Python")
        assert good is not None
        bad = good.model_copy(update={"text": "Rust"})
        verified, rejected = verify_all([good, bad], RESUME)
        assert verified == [good]
        assert rejected == [bad]


class TestPrompt:
    def test_the_resume_is_delimited(self) -> None:
        prompt = build_prompt(RESUME, sectionize(normalize(RESUME), extract_stub()))
        assert "<resume>" in prompt and "</resume>" in prompt

    def test_the_prompt_forbids_invention(self) -> None:
        prompt = build_prompt(RESUME, sectionize(normalize(RESUME), extract_stub()))
        assert "Never" in prompt or "never" in prompt
        assert "verbatim" in prompt.lower()

    def test_embedded_instructions_are_declared_to_be_data(self) -> None:
        prompt = build_prompt(RESUME, sectionize(normalize(RESUME), extract_stub()))
        assert "not directions for you" in prompt

    def test_very_long_input_is_capped(self) -> None:
        prompt = build_prompt("x" * 100_000, sectionize(normalize(RESUME), extract_stub()))
        assert len(prompt) < 30_000


def extract_stub() -> ExtractedDocument:
    """Minimal stand-in: these tests exercise conversion, not typography."""
    return ExtractedDocument(text=RESUME, lines=[], page_count=1)


class TestConversion:
    def _convert(self, raw: LlmResume) -> tuple[ResumeDocument, list[str]]:
        normalized = normalize(RESUME)
        sections = sectionize(normalized, extract_stub())
        return to_document(
            raw,
            source=RESUME,
            contact=extract_contact(RESUME),
            sections=sections,
            page_count=1,
        )

    def test_verified_bullets_are_kept(self) -> None:
        document, unverified = self._convert(
            LlmResume(
                experience=[
                    LlmExperience(
                        title="Software Engineering Intern",
                        organization="Zentara Technologies",
                        dates="June 2025 - August 2025",
                        bullets=["Reduced p95 API latency from 820ms to 210ms"],
                    )
                ]
            )
        )
        assert len(document.experience[0].bullets) == 1
        assert unverified == []

    def test_invented_bullets_are_dropped(self) -> None:
        document, unverified = self._convert(
            LlmResume(
                experience=[
                    LlmExperience(
                        title="Software Engineering Intern",
                        bullets=[
                            "Reduced p95 API latency from 820ms to 210ms",
                            "Managed a team of fifteen engineers",
                        ],
                    )
                ]
            )
        )
        assert len(document.experience[0].bullets) == 1
        assert "Managed a team of fifteen engineers" in unverified

    def test_an_invented_employer_is_dropped(self) -> None:
        document, _ = self._convert(
            LlmResume(experience=[LlmExperience(title="Engineer", organization="Google")])
        )
        assert document.experience[0].organization is None

    def test_dates_are_parsed_rather_than_trusted(self) -> None:
        document, _ = self._convert(
            LlmResume(experience=[LlmExperience(title="Intern", dates="June 2025 - August 2025")])
        )
        dates = document.experience[0].dates
        assert (dates.start_year, dates.start_month) == (2025, 6)
        assert dates.months == 2

    def test_invented_skills_are_dropped(self) -> None:
        document, unverified = self._convert(LlmResume(skills=["Python", "SQL", "Kubernetes"]))
        assert {skill.raw for skill in document.skills} == {"Python", "SQL"}
        assert "Kubernetes" in unverified

    def test_skill_origin_is_taken_from_where_it_was_found(self) -> None:
        """The distinction the whole scoring model rests on."""
        document, _ = self._convert(LlmResume(skills=["Python"]))
        assert document.skills[0].origin in {
            SkillOrigin.SKILLS_LIST,
            SkillOrigin.EXPERIENCE_BULLET,
        }

    def test_every_kept_bullet_has_a_verifiable_span(self) -> None:
        document, _ = self._convert(
            LlmResume(
                experience=[
                    LlmExperience(
                        title="Intern",
                        bullets=["Reduced p95 API latency from 820ms to 210ms"],
                    )
                ],
                projects=[LlmProject(name="Thing", bullets=["Built a Django REST service"])],
            )
        )
        for item in document.experience:
            for bullet in item.bullets:
                assert bullet.span is not None
                assert bullet.span.verify(RESUME)

    def test_education_is_converted(self) -> None:
        document, _ = self._convert(
            LlmResume(education=[LlmEducation(degree="B.Tech", institution="Nowhere")])
        )
        assert document.education[0].institution is None  # not in the resume

    def test_empty_output_produces_an_empty_document(self) -> None:
        document, unverified = self._convert(LlmResume())
        assert document.experience == []
        assert unverified == []

    def test_spans_are_relative_to_the_resume(self) -> None:
        document, _ = self._convert(LlmResume(skills=["Python"]))
        assert document.skills[0].span is not None
        assert document.skills[0].span.doc is SourceDoc.RESUME


class TestConfidence:
    def _assess(
        self, resumes: Path, name: str, *, unverified: int = 0, reported: int = 10
    ) -> ConfidenceBreakdown:
        extracted, normalized, sections = parsed(resumes, name)
        document, _ = to_document(
            LlmResume(
                experience=[
                    LlmExperience(
                        title="Software Engineering Intern",
                        bullets=["Built a Django REST service handling 40,000 requests per day"],
                    )
                ],
                skills=["Python", "Django"],
            ),
            source=normalized.text,
            contact=extract_contact(normalized.text),
            sections=sections,
            page_count=extracted.page_count,
        )
        return assess(
            extracted=extracted,
            sections=sections,
            document=document,
            unverified_count=unverified,
            reported_count=reported,
        )

    def test_a_clean_resume_scores_well(self, synthetic_resumes: Path) -> None:
        breakdown = self._assess(synthetic_resumes, "single-column-classic.pdf")
        assert breakdown.score > 0.6

    def test_heavy_hallucination_drags_the_score_down(self, synthetic_resumes: Path) -> None:
        """The strongest signal that structured output cannot be trusted."""
        clean = self._assess(synthetic_resumes, "single-column-classic.pdf")
        noisy = self._assess(
            synthetic_resumes, "single-column-classic.pdf", unverified=9, reported=10
        )
        assert noisy.score < clean.score

    def test_a_sparse_resume_scores_lower_than_a_full_one(self, synthetic_resumes: Path) -> None:
        full = self._assess(synthetic_resumes, "single-column-classic.pdf")
        sparse = self._assess(synthetic_resumes, "sparse-minimal.pdf")
        assert sparse.score < full.score

    def test_the_score_stays_in_range(self, synthetic_resumes: Path) -> None:
        breakdown = self._assess(
            synthetic_resumes, "single-column-classic.pdf", unverified=100, reported=10
        )
        assert 0.0 <= breakdown.score <= 1.0

    def test_the_weakest_component_is_identified(self) -> None:
        breakdown = ConfidenceBreakdown(
            text_density=0.9,
            section_detection=0.1,
            contact_completeness=0.9,
            span_verification=0.9,
            content_present=0.9,
        )
        assert breakdown.weakest == "section_detection"


class TestConfidenceExplanations:
    def test_a_high_score_needs_no_explanation(self) -> None:
        breakdown = ConfidenceBreakdown(1.0, 1.0, 1.0, 1.0, 1.0)
        assert breakdown.score >= HIGH_CONFIDENCE
        assert explain(breakdown) is None

    def test_a_low_score_is_marked_provisional(self) -> None:
        breakdown = ConfidenceBreakdown(0.1, 0.1, 0.1, 0.1, 0.1)
        assert breakdown.score < LOW_CONFIDENCE
        message = explain(breakdown)
        assert message is not None
        assert message.startswith("Results are provisional")

    def test_the_explanation_names_the_actual_problem(self) -> None:
        breakdown = ConfidenceBreakdown(
            text_density=0.1,
            section_detection=0.9,
            contact_completeness=0.9,
            span_verification=0.9,
            content_present=0.9,
        )
        message = explain(breakdown)
        assert message is not None
        assert "text" in message.lower()

    @pytest.mark.parametrize(
        "weakest",
        ["text_density", "section_detection", "contact_completeness", "content_present"],
    )
    def test_every_component_has_an_explanation(self, weakest: str) -> None:
        values = dict.fromkeys(
            [
                "text_density",
                "section_detection",
                "contact_completeness",
                "span_verification",
                "content_present",
            ],
            0.9,
        )
        values[weakest] = 0.05
        breakdown = ConfidenceBreakdown(**values)
        assert explain(breakdown) is not None
