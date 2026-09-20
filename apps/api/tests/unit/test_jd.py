"""Tests for JD cleaning, priority cues and the skill taxonomy.

Run against the fifteen fixture postings, each written to exercise a specific
behaviour, plus their hand-written ground truth in manifest.yaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from roleva.api.errors import ErrorCode, RolevaError
from roleva.jd.cleaner import clean
from roleva.jd.cues import (
    find_quantifier,
    is_negated,
    priority_from_heading,
    priority_from_text,
    resolve_priority,
)
from roleva.matching.taxonomy import (
    find_in_text,
    is_adjacent,
    normalise,
    resolve,
)
from roleva.models.job import Priority

JD_DIR = Path(__file__).parents[1] / "fixtures" / "jds"


def jd(name: str) -> str:
    return (JD_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def manifest() -> list[dict[str, Any]]:
    data = yaml.safe_load((JD_DIR / "manifest.yaml").read_text(encoding="utf-8"))
    fixtures: list[dict[str, Any]] = data["fixtures"]
    return fixtures


class TestLengthValidation:
    def test_a_too_short_posting_is_rejected(self) -> None:
        with pytest.raises(RolevaError) as exc:
            clean(jd("too-short-reject.txt"))
        assert exc.value.code is ErrorCode.JD_TOO_SHORT

    def test_a_marginal_posting_is_accepted_but_flagged(self) -> None:
        result = clean(jd("marginal-length-warn.txt"))
        assert result.is_thin is True

    def test_a_full_posting_is_not_flagged(self) -> None:
        assert clean(jd("sde-intern-classic.txt")).is_thin is False


class TestBoilerplateRemoval:
    """Roughly half a corporate posting is not about the job."""

    def test_benefits_and_eeo_text_are_stripped(self) -> None:
        result = clean(jd("sde-entry-boilerplate.txt"))
        lowered = result.text.lower()
        for noise in ("401(k)", "dental", "unlimited paid time off", "equal opportunity"):
            assert noise not in lowered

    def test_the_actual_requirements_survive(self) -> None:
        result = clean(jd("sde-entry-boilerplate.txt"))
        for kept in ("Java", "Spring Boot", "SQL", "Kafka"):
            assert kept in result.text

    def test_application_instructions_are_stripped(self) -> None:
        result = clean(jd("sde-entry-boilerplate.txt"))
        assert "careers portal" not in result.text.lower()

    def test_cleaning_removes_a_substantial_share(self) -> None:
        result = clean(jd("sde-entry-boilerplate.txt"))
        assert result.removed_chars > 500

    def test_a_posting_with_no_boilerplate_is_left_alone(self) -> None:
        result = clean(jd("sde-intern-classic.txt"))
        assert "Python" in result.text
        assert result.removed_chars < 200

    def test_cleaning_never_empties_a_posting(self) -> None:
        """If the heuristics ate everything, the original is a safer input."""
        result = clean(jd("marginal-length-warn.txt"))
        assert len(result.text) > 100

    @pytest.mark.parametrize(
        "name",
        [
            "sde-intern-classic.txt",
            "sde-entry-prose.txt",
            "data-analyst-entry.txt",
            "product-intern.txt",
            "ux-design-entry.txt",
            "ml-engineer-entry-mixed.txt",
        ],
    )
    def test_cleaning_preserves_the_whole_corpus(self, name: str) -> None:
        result = clean(jd(name))
        assert len(result.text) > 300


class TestQuantifiers:
    @pytest.mark.parametrize(
        ("text", "years"),
        [
            ("3+ years of Python", 3.0),
            ("at least 2 years of experience", 2.0),
            ("minimum of 5 years", 5.0),
            ("2-4 years in a similar role", 2.0),
            ("one year of hands-on experience", 1.0),
            ("At least 1 year of experience with Python", 1.0),
        ],
    )
    def test_years_are_extracted(self, text: str, years: float) -> None:
        quantifier = find_quantifier(text)
        assert quantifier is not None
        assert quantifier.years == years

    def test_text_without_a_quantifier_yields_none(self) -> None:
        assert find_quantifier("Strong Python fundamentals") is None

    def test_the_raw_wording_is_kept(self) -> None:
        quantifier = find_quantifier("3+ years of Python")
        assert quantifier is not None and "3" in (quantifier.raw or "")


class TestNegation:
    @pytest.mark.parametrize(
        "text",
        [
            "A PhD is not required",
            "A research background is not required",
            "no prior experience necessary",
            "Familiarity with bioinformatics is not a requirement",
        ],
    )
    def test_negations_are_detected(self, text: str) -> None:
        assert is_negated(text) is True

    def test_an_ordinary_requirement_is_not_negated(self) -> None:
        assert is_negated("Strong Python required") is False


class TestPriorityCues:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Python is required", Priority.MUST),
            ("You must have SQL", Priority.MUST),
            ("Minimum: a Bachelor's degree", Priority.MUST),
            ("Docker is preferred", Priority.NICE),
            ("Kubernetes is a plus", Priority.NICE),
            ("Terraform would be great", Priority.NICE),
            ("Experience deploying a model is strongly preferred", Priority.STRONG),
            ("You should have SQL", Priority.STRONG),
        ],
    )
    def test_wording_sets_priority(self, text: str, expected: Priority) -> None:
        assert priority_from_text(text) is expected

    def test_strongly_preferred_is_not_merely_nice(self) -> None:
        """Three tiers carry information that collapsing to two would lose."""
        assert priority_from_text("strongly preferred") is Priority.STRONG
        assert priority_from_text("preferred") is Priority.NICE

    @pytest.mark.parametrize(
        ("heading", "expected"),
        [
            ("Required qualifications", Priority.MUST),
            ("Requirements", Priority.MUST),
            ("Must have", Priority.MUST),
            ("Essential criteria", Priority.MUST),
            ("What you need", Priority.MUST),
            ("Preferred qualifications", Priority.NICE),
            ("Nice to have", Priority.NICE),
            ("Bonus", Priority.NICE),
            ("Desirable", Priority.NICE),
            ("Strongly preferred", Priority.STRONG),
        ],
    )
    def test_headings_set_priority_for_what_follows(self, heading: str, expected: Priority) -> None:
        assert priority_from_heading(heading) is expected

    def test_an_unrelated_heading_sets_nothing(self) -> None:
        assert priority_from_heading("Responsibilities") is None


class TestPriorityResolution:
    def test_a_negation_wins_over_everything(self) -> None:
        result = resolve_priority(
            proposed=Priority.MUST,
            text="A PhD is not required",
            heading="Requirements",
        )
        assert result.priority is Priority.NICE
        assert result.from_rule is True

    def test_the_job_title_makes_a_skill_mandatory(self) -> None:
        result = resolve_priority(proposed=Priority.NICE, text="Python", in_job_title=True)
        assert result.priority is Priority.MUST

    def test_wording_beats_the_heading(self) -> None:
        """A "preferred" item under a Requirements heading is still preferred."""
        result = resolve_priority(
            proposed=Priority.MUST,
            text="Docker is preferred",
            heading="Requirements",
        )
        assert result.priority is Priority.NICE

    def test_the_heading_applies_when_wording_is_silent(self) -> None:
        result = resolve_priority(
            proposed=Priority.NICE, text="PostgreSQL", heading="Required qualifications"
        )
        assert result.priority is Priority.MUST

    def test_repetition_escalates(self) -> None:
        result = resolve_priority(proposed=Priority.NICE, text="Python", mention_count=3)
        assert result.priority is Priority.STRONG

    def test_the_model_is_trusted_when_no_rule_fires(self) -> None:
        result = resolve_priority(proposed=Priority.STRONG, text="PostgreSQL")
        assert result.priority is Priority.STRONG
        assert result.from_rule is False

    def test_every_decision_carries_a_reason(self) -> None:
        result = resolve_priority(proposed=Priority.NICE, text="SQL", heading="Requirements")
        assert "Requirements" in result.reason


class TestTaxonomyResolution:
    @pytest.mark.parametrize(
        ("written", "canonical"),
        [
            ("k8s", "Kubernetes"),
            ("K8s", "Kubernetes"),
            ("JS", "JavaScript"),
            ("postgres", "PostgreSQL"),
            ("Postgres", "PostgreSQL"),
            ("node", "Node.js"),
            ("nodejs", "Node.js"),
            ("react.js", "React"),
            ("golang", "Go"),
            ("sklearn", "scikit-learn"),
            ("ML", "Machine Learning"),
            ("tailwindcss", "Tailwind CSS"),
            ("b.tech", "Bachelor's Degree"),
            ("a11y", "Accessibility"),
        ],
    )
    def test_aliases_resolve_to_canonical_names(self, written: str, canonical: str) -> None:
        result = resolve(written)
        assert result is not None
        assert result.canonical == canonical

    def test_an_exact_match_is_marked_exact(self) -> None:
        result = resolve("Python")
        assert result is not None and result.exact is True

    def test_a_typo_still_resolves(self) -> None:
        result = resolve("Kubernets")
        assert result is not None
        assert result.canonical == "Kubernetes"
        assert result.exact is False

    def test_java_and_javascript_stay_distinct(self) -> None:
        """The threshold exists for exactly this pair."""
        assert resolve("Java").canonical == "Java"  # type: ignore[union-attr]
        assert resolve("JavaScript").canonical == "JavaScript"  # type: ignore[union-attr]

    def test_an_unknown_skill_resolves_to_nothing(self) -> None:
        assert resolve("Blorbotron 9000") is None

    def test_empty_input_resolves_to_nothing(self) -> None:
        assert resolve("") is None

    def test_punctuation_that_carries_meaning_is_kept(self) -> None:
        assert normalise("C++") == "c++"
        assert normalise("Next.js") == "next.js"
        assert normalise(".NET") == ".net"


class TestFindingSkillsInText:
    def test_skills_are_found_in_a_sentence(self) -> None:
        found = {name for name, _, _ in find_in_text("Built a Django REST service in Python")}
        assert {"Django", "Python"} <= found

    def test_the_longest_name_wins(self) -> None:
        """ "Machine Learning" is one skill, not "Learning" plus noise."""
        found = [name for name, _, _ in find_in_text("Experience with machine learning")]
        assert "Machine Learning" in found

    def test_a_single_letter_skill_does_not_match_everything(self) -> None:
        """R is a real skill name and a very common letter."""
        found = [name for name, _, _ in find_in_text("Rewrote the parser for better results")]
        assert "R" not in found

    def test_positions_are_reported(self) -> None:
        found = find_in_text("Python and SQL")
        assert all(start < end for _, start, end in found)

    def test_overlapping_matches_are_claimed_once(self) -> None:
        found = [name for name, _, _ in find_in_text("scikit-learn and machine learning")]
        assert found.count("Machine Learning") <= 1


class TestAdjacency:
    def test_related_frameworks_are_adjacent(self) -> None:
        assert is_adjacent("React", "Vue.js") is True
        assert is_adjacent("AWS", "Azure") is True

    def test_adjacency_is_not_equivalence(self) -> None:
        """Telling someone they satisfy a React requirement because they know
        Vue would be a lie they might act on."""
        assert resolve("Vue").canonical != "React"  # type: ignore[union-attr]

    def test_unrelated_skills_are_not_adjacent(self) -> None:
        assert is_adjacent("React", "PostgreSQL") is False


class TestAgainstTheManifest:
    def test_expected_requirements_appear_in_the_cleaned_text(
        self, manifest: list[dict[str, Any]]
    ) -> None:
        """Every requirement the ground truth expects must survive cleaning —
        otherwise extraction cannot possibly find it."""
        for entry in manifest:
            if entry.get("expect_error"):
                continue
            cleaned = clean(jd(entry["file"])).text.lower()
            for requirement in entry.get("must_include", []):
                assert requirement["text"].lower() in cleaned, (
                    f"{entry['file']}: {requirement['text']} lost during cleaning"
                )

    def test_forbidden_text_is_gone(self, manifest: list[dict[str, Any]]) -> None:
        for entry in manifest:
            for forbidden in entry.get("must_not_include", []):
                cleaned = clean(jd(entry["file"])).text.lower()
                assert forbidden.lower() not in cleaned, (
                    f"{entry['file']}: {forbidden} survived cleaning"
                )


class TestLongestHeadingMatchWins:
    """ "Preferred qualifications" contains "qualifications", a must-have cue.
    Tier order alone turned every optional item into a requirement."""

    @pytest.mark.parametrize(
        ("heading", "expected"),
        [
            ("Preferred qualifications", Priority.NICE),
            ("Required qualifications", Priority.MUST),
            ("Minimum qualifications", Priority.MUST),
            ("Strongly preferred", Priority.STRONG),
            ("Preferred", Priority.NICE),
        ],
    )
    def test_the_most_specific_phrase_decides(self, heading: str, expected: Priority) -> None:
        assert priority_from_heading(heading) is expected


class TestRequirementsCanonicaliseFromSentences:
    """Found by the first live end-to-end run.

    A real posting writes "3+ years of experience with Python required", not
    "Python". `resolve` only recognises a string that *is* a skill name, so
    every requirement came back with `canonical = None` — and because every tier
    of the matching cascade resolves `canonical or text`, tiers 1 and 2 could
    never fire. Fourteen requirements, zero matches, against a resume that
    plainly had several of them.

    The offline tests missed it because the scripted extractor returned tidy
    one-word requirements. The fixture was unrealistic in exactly the way that
    hid the bug.
    """

    def test_a_skill_named_in_a_sentence_is_found(self) -> None:
        from roleva.jd.requirement_extractor import _canonical_for

        assert _canonical_for("3+ years of experience with Python required") == "Python"
        assert _canonical_for("Strong SQL and relational database design") == "SQL"

    def test_a_bare_skill_name_still_works(self) -> None:
        from roleva.jd.requirement_extractor import _canonical_for

        assert _canonical_for("Kubernetes") == "Kubernetes"

    def test_a_sentence_naming_no_known_skill_stays_unresolved(self) -> None:
        from roleva.jd.requirement_extractor import _canonical_for

        assert _canonical_for("2+ years of professional backend experience") is None

    def test_several_skills_are_left_for_the_adjudicator(self) -> None:
        """ "at least one of AWS, GCP or Azure" is satisfied by any of them.

        Picking the first would under-match a resume that has the second, so the
        ambiguity is preserved rather than resolved arbitrarily.
        """
        from roleva.jd.requirement_extractor import _canonical_for

        assert (
            _canonical_for("Experience with at least one cloud provider (AWS, GCP or Azure)")
            is None
        )

    def test_it_is_deterministic(self) -> None:
        """`find_in_text` returns a set internally; a set with one element has
        one order, but the guard against relying on that is worth keeping."""
        from roleva.jd.requirement_extractor import _canonical_for

        text = "Strong SQL and relational database design"
        assert len({_canonical_for(text) for _ in range(20)}) == 1
