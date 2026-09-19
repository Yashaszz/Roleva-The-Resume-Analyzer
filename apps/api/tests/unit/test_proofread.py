"""Proofreading flags.

Most of these tests are about what must *not* be flagged. A proofreader that
finds real errors is easy; one a user trusts has to be silent about correct text,
including surnames, British spellings and technology names it has never seen.
"""

from __future__ import annotations

import pytest

from roleva.models.common import SourceDoc, Span
from roleva.models.resume import Bullet, ExperienceItem, ResumeDocument
from roleva.quality.proofread import (
    MAX_FLAGS,
    MISSPELLINGS,
    TECHNOLOGY_CASING,
    FlagKind,
    FlagSeverity,
    proofread,
)


def _doc(*bullets: str, summary: str | None = None) -> ResumeDocument:
    document = ResumeDocument(
        experience=[
            ExperienceItem(
                title="Engineer",
                bullets=[Bullet(text=text) for text in bullets],
            )
        ]
    )
    if summary is not None:
        document.summary = Bullet(text=summary)
    return document


def _kinds(*bullets: str) -> set[FlagKind]:
    return {flag.kind for flag in proofread(_doc(*bullets)).flags}


class TestMisspellings:
    def test_a_known_misspelling_is_flagged(self) -> None:
        report = proofread(_doc("Recieved an award for the migration project"))
        flag = next(f for f in report.flags if f.kind is FlagKind.MISSPELLING)
        assert flag.found == "Recieved"
        assert "Received" in flag.fix
        assert flag.severity is FlagSeverity.ERROR

    def test_the_suggestion_keeps_the_writers_capitalisation(self) -> None:
        upper = proofread(_doc("Seperate services were deployed")).flags[0]
        lower = proofread(_doc("Built seperate services for each tenant")).flags[0]
        assert 'Use "Separate"' in upper.fix
        assert 'Use "separate"' in lower.fix

    def test_every_entry_actually_changes_the_word(self) -> None:
        """A map entry where key == value would flag correct spelling forever."""
        for wrong, right in MISSPELLINGS.items():
            assert wrong != right.lower(), wrong


class TestWhatMustNotBeFlagged:
    @pytest.mark.parametrize(
        "text",
        [
            "Optimised the analyser and standardised the behaviour of the programme",
            "Centralised authorisation and modernised the catalogue",
            "Recognised for prioritising the organisation's licence renewal",
        ],
    )
    def test_british_spellings_are_correct(self, text: str) -> None:
        """A British-spelling resume is not a resume full of errors."""
        assert not proofread(_doc(text)).flags

    @pytest.mark.parametrize(
        "surname",
        ["Raghavendra", "Zentara", "Nkemelu", "Oyelaran", "Bhattacharya", "Wojciechowski"],
    )
    def test_proper_nouns_are_not_spelling_mistakes(self, surname: str) -> None:
        assert not proofread(_doc(f"Reported to {surname} on the platform team")).flags

    def test_no_correctly_spelled_technology_is_ever_flagged(self) -> None:
        """The constraint that motivated the closed-set design."""
        for name in TECHNOLOGY_CASING:
            report = proofread(_doc(f"Built services with {name} in production"))
            assert not report.flags, f"{name} was flagged: {report.flags}"

    def test_ordinary_english_words_are_not_treated_as_products(self) -> None:
        """ "Excel at" must not become "Excel at"."""
        assert not _kinds("Excel at communication and rust removal from the swift build")

    def test_a_url_is_not_a_casing_error(self) -> None:
        assert not _kinds("Published the library at github.com/example/repo")

    def test_a_versioned_command_is_not_a_casing_error(self) -> None:
        assert not _kinds("Migrated the service to python3 and ran the suite")

    def test_thousands_separators_survive(self) -> None:
        assert not _kinds("Served 40,000 requests per day at 99.9% availability")

    def test_ellipsis_is_not_repeated_punctuation(self) -> None:
        assert FlagKind.REPEATED_PUNCTUATION not in _kinds("Shipped the feature... eventually")

    def test_legitimate_repeats_are_allowed(self) -> None:
        assert FlagKind.DOUBLED_WORD not in _kinds("Ensured that that release had had approval")


class TestPunctuationAndStructure:
    def test_a_doubled_word_is_flagged(self) -> None:
        flag = next(
            f
            for f in proofread(_doc("Built the the payment service")).flags
            if f.kind is FlagKind.DOUBLED_WORD
        )
        assert "Delete" in flag.fix

    def test_a_space_before_a_comma_is_flagged(self) -> None:
        assert FlagKind.SPACE_BEFORE_PUNCTUATION in _kinds("Built services , tested them")

    def test_a_missing_space_after_a_comma_is_flagged(self) -> None:
        assert FlagKind.MISSING_SPACE in _kinds("Used Python,Django and Redis in production")

    def test_repeated_punctuation_is_polish_not_error(self) -> None:
        report = proofread(_doc("Shipped it on time!!"))
        flag = next(f for f in report.flags if f.kind is FlagKind.REPEATED_PUNCTUATION)
        assert flag.severity is FlagSeverity.POLISH

    def test_an_unclosed_bracket_is_flagged(self) -> None:
        assert FlagKind.UNBALANCED_BRACKETS in _kinds("Built the parser (in Python for the team")

    def test_balanced_brackets_are_not_flagged(self) -> None:
        assert FlagKind.UNBALANCED_BRACKETS not in _kinds("Built the parser (in Python) for us")

    def test_a_lowercase_opening_word_is_flagged(self) -> None:
        assert FlagKind.LOWERCASE_START in _kinds("built the payment service end to end")

    def test_a_technology_opening_a_bullet_is_not_a_lowercase_start(self) -> None:
        """ "iOS release shipped" opens lowercase and is correct."""
        assert FlagKind.LOWERCASE_START not in _kinds("iOS release shipped ahead of schedule")


class TestCasing:
    def test_a_miscased_technology_is_flagged(self) -> None:
        flag = next(
            f
            for f in proofread(_doc("Wrote Javascript for the checkout flow")).flags
            if f.kind is FlagKind.TECHNOLOGY_CASING
        )
        assert flag.found == "Javascript"
        assert "JavaScript" in flag.fix
        assert flag.severity is FlagSeverity.POLISH

    def test_lowercase_technology_names_are_flagged(self) -> None:
        assert FlagKind.TECHNOLOGY_CASING in _kinds("Deployed with kubernetes and postgresql")


class TestTerminatorConsistency:
    def test_mixed_terminators_are_reported(self) -> None:
        report = proofread(
            _doc(
                "Built the payment service.",
                "Reduced latency by half.",
                "Wrote the migration guide.",
                "Mentored two interns.",
                "Shipped the release",
            )
        )
        assert FlagKind.INCONSISTENT_TERMINATORS in {f.kind for f in report.flags}

    def test_a_consistent_document_is_not_reported(self) -> None:
        report = proofread(
            _doc(
                "Built the payment service.",
                "Reduced latency by half.",
                "Wrote the migration guide.",
                "Mentored two interns.",
            )
        )
        assert FlagKind.INCONSISTENT_TERMINATORS not in {f.kind for f in report.flags}

    def test_a_genuinely_mixed_document_is_left_alone(self) -> None:
        """Half and half is a style, not a slip. Only outliers are reported."""
        report = proofread(
            _doc(
                "Built the payment service.",
                "Reduced latency by half.",
                "Wrote the migration guide",
                "Mentored two interns",
            )
        )
        assert FlagKind.INCONSISTENT_TERMINATORS not in {f.kind for f in report.flags}

    def test_too_few_bullets_to_judge(self) -> None:
        report = proofread(_doc("Built the payment service.", "Shipped the release"))
        assert FlagKind.INCONSISTENT_TERMINATORS not in {f.kind for f in report.flags}


class TestReportShape:
    def test_repeats_collapse_into_one_flag_with_a_count(self) -> None:
        report = proofread(
            _doc(
                "Recieved the award",
                "Recieved a second award",
                "Recieved a third award",
            )
        )
        spelling = [f for f in report.flags if f.kind is FlagKind.MISSPELLING]
        assert len(spelling) == 1
        assert spelling[0].occurrences == 3

    def test_output_is_capped_but_records_the_true_total(self) -> None:
        noisy = [f"bullet {word} about seperate things" for word in MISSPELLINGS]
        report = proofread(_doc(*noisy))
        assert len(report.flags) <= MAX_FLAGS
        assert report.total_found > MAX_FLAGS

    def test_errors_are_ranked_above_polish(self) -> None:
        report = proofread(
            _doc(
                "wrote Javascript for the flow",
                "Recieved the award",
                "built the the service",
            )
        )
        severities = [flag.severity for flag in report.flags]
        assert severities == sorted(severities, key=lambda s: s is not FlagSeverity.ERROR)

    def test_the_summary_is_proofread_too(self) -> None:
        report = proofread(_doc("Built the service.", summary="Enviroment-focused engineer"))
        assert any(f.found == "Enviroment" for f in report.flags)

    def test_an_empty_document_produces_nothing(self) -> None:
        assert not proofread(ResumeDocument()).flags

    def test_it_is_deterministic(self) -> None:
        document = _doc("Recieved the award", "wrote Javascript , badly")
        first = [(f.kind, f.found, f.local_start) for f in proofread(document).flags]
        for _ in range(9):
            assert [(f.kind, f.found, f.local_start) for f in proofread(document).flags] == first


class TestSpans:
    def test_a_flag_span_verifies_against_the_source(self) -> None:
        """The product rule: every displayed quote must be findable verbatim."""
        source = "Header\nRecieved an award for the work\nFooter"
        start = source.index("Recieved")
        text = "Recieved an award for the work"
        document = ResumeDocument(
            experience=[
                ExperienceItem(
                    title="Engineer",
                    bullets=[
                        Bullet(
                            text=text,
                            span=Span(
                                doc=SourceDoc.RESUME,
                                start=start,
                                end=start + len(text),
                                text=text,
                            ),
                        )
                    ],
                )
            ]
        )
        flag = next(f for f in proofread(document).flags if f.kind is FlagKind.MISSPELLING)
        assert flag.span is not None
        assert flag.span.verify(source)

    def test_no_span_is_produced_when_the_offsets_cannot_be_trusted(self) -> None:
        """A stale span must yield no span rather than a wrong one."""
        document = ResumeDocument(
            experience=[
                ExperienceItem(
                    title="Engineer",
                    bullets=[
                        Bullet(
                            text="Recieved an award",
                            span=Span(
                                doc=SourceDoc.RESUME,
                                start=0,
                                end=9,
                                text="different",
                            ),
                        )
                    ],
                )
            ]
        )
        flag = next(f for f in proofread(document).flags if f.kind is FlagKind.MISSPELLING)
        assert flag.span is None


class TestFlagsDoNotAffectTheScore:
    def test_proofreading_is_absent_from_the_rubric(self) -> None:
        """Flagging is advisory by decision: a false positive must not cost points."""
        from roleva.scoring.engine import load_rubric

        rubric = load_rubric()
        assert "spelling" not in rubric["metric_weights"]
        assert "grammar" not in rubric["metric_weights"]
