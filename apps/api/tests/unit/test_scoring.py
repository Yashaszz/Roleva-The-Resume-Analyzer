"""Tests for the scoring engine.

The engine is a pure function, so these are exact assertions — no tolerance
bands, no retries, no flakiness. If a number here moves, the rubric changed,
and that should be visible in the diff.
"""

from __future__ import annotations

import pytest

from roleva.models.ats import AtsFinding, AtsReport, AtsRuleId, AtsSeverity
from roleva.models.common import Provenance, SourceDoc, Span
from roleva.models.evidence import Evidence, MatchReport, MatchStatus, RequirementMatch
from roleva.models.job import JobTarget, Priority, Requirement, RequirementCategory, Seniority
from roleva.models.resume import Bullet, DateRange, ExperienceItem, ResumeDocument, SkillOrigin
from roleva.models.scoring import Band, ScoreKind
from roleva.quality.metrics import measure
from roleva.quality.rubric_judge import (
    ANCHORS,
    LlmRubric,
    build_prompt,
    describe,
    to_judgement,
)
from roleva.scoring.engine import (
    RubricJudgement,
    compute,
    load_rubric,
    score_ats,
    score_job_match,
    summarise_coverage,
)

RUBRIC = load_rubric()


def requirement(text: str, priority: Priority = Priority.MUST) -> Requirement:
    return Requirement(text=text, category=RequirementCategory.HARD_SKILL, priority=priority)


def matched(req: Requirement, strength: float) -> RequirementMatch:
    status = (
        MatchStatus.MISSING
        if strength == 0
        else MatchStatus.MATCHED
        if strength > 0.5
        else MatchStatus.PARTIAL
    )
    evidence = (
        [
            Evidence(
                span=Span(doc=SourceDoc.RESUME, start=0, end=6, text="Python"),
                origin=SkillOrigin.EXPERIENCE_BULLET,
                provenance=Provenance.LEXICAL,
            )
        ]
        if strength > 0
        else []
    )
    return RequirementMatch(
        requirement_id=req.id, status=status, strength=strength, evidence=evidence
    )


def good_document() -> ResumeDocument:
    return ResumeDocument(
        experience=[
            ExperienceItem(
                title="Engineer",
                dates=DateRange(start_year=2024, end_year=2025),
                bullets=[
                    Bullet(text="Built a Django service handling 40,000 requests per day"),
                    Bullet(text="Reduced p95 latency from 820ms to 210ms by adding indexes"),
                    Bullet(text="Wrote 60 unit tests, raising coverage from 34% to 81%"),
                ],
            )
        ]
    )


def poor_document() -> ResumeDocument:
    return ResumeDocument(
        experience=[
            ExperienceItem(
                title="Engineer",
                bullets=[
                    Bullet(text="Responsible for the website"),
                    Bullet(text="Worked on various tasks"),
                    Bullet(text="I was involved in testing"),
                ],
            )
        ]
    )


class TestJobMatch:
    def test_full_coverage_scores_one_hundred(self) -> None:
        reqs = [requirement("Python"), requirement("SQL")]
        job = JobTarget(requirements=reqs)
        matches = MatchReport(matches=[matched(r, 1.0) for r in reqs])

        score, must, overall = score_job_match(job, matches, RUBRIC)
        assert score.value == 100.0
        assert must == 1.0
        assert overall == 1.0

    def test_nothing_matched_scores_zero(self) -> None:
        reqs = [requirement("Python")]
        score, must, _ = score_job_match(
            JobTarget(requirements=reqs), MatchReport(matches=[matched(reqs[0], 0.0)]), RUBRIC
        )
        assert score.value == 0.0
        assert must == 0.0

    def test_priority_weighting_is_applied(self) -> None:
        """A must-have is worth three times a nice-to-have."""
        must = requirement("Python", Priority.MUST)
        nice = requirement("Docker", Priority.NICE)
        job = JobTarget(requirements=[must, nice])

        only_must = score_job_match(
            job, MatchReport(matches=[matched(must, 1.0), matched(nice, 0.0)]), RUBRIC
        )[0]
        only_nice = score_job_match(
            job, MatchReport(matches=[matched(must, 0.0), matched(nice, 1.0)]), RUBRIC
        )[0]

        assert only_must.value == 75.0  # 3 of 4 weight
        assert only_nice.value == 25.0  # 1 of 4 weight

    def test_partial_strength_earns_partial_credit(self) -> None:
        req = requirement("Docker")
        score, _, _ = score_job_match(
            JobTarget(requirements=[req]), MatchReport(matches=[matched(req, 0.5)]), RUBRIC
        )
        assert score.value == 50.0

    def test_every_requirement_becomes_a_component(self) -> None:
        reqs = [requirement("Python"), requirement("SQL"), requirement("Docker")]
        score, _, _ = score_job_match(
            JobTarget(requirements=reqs),
            MatchReport(matches=[matched(r, 1.0) for r in reqs]),
            RUBRIC,
        )
        assert len(score.components) == 3

    def test_an_empty_job_does_not_divide_by_zero(self) -> None:
        score, must, overall = score_job_match(JobTarget(), MatchReport(), RUBRIC)
        assert score.value == 0.0
        assert (must, overall) == (0.0, 0.0)


class TestMustHaveGate:
    """Without this, twelve nice-to-haves and zero must-haves reads as
    competitive — advice that would waste somebody's time."""

    def _job_with(self, must_strength: float) -> tuple[JobTarget, MatchReport]:
        """Two must-haves against twenty nice-to-haves.

        Weighted, the optional requirements outweigh the essential ones six to
        one, so matching all of them and none of the must-haves scores 77 —
        which is exactly the misleading result the gate exists to prevent.
        """
        musts = [requirement(f"Must {i}", Priority.MUST) for i in range(2)]
        nices = [requirement(f"Nice {i}", Priority.NICE) for i in range(20)]
        matches = [matched(m, must_strength) for m in musts] + [matched(n, 1.0) for n in nices]
        return JobTarget(requirements=musts + nices), MatchReport(matches=matches)

    def test_missing_most_must_haves_caps_the_score(self) -> None:
        job, matches = self._job_with(0.0)
        score, must_coverage, _ = score_job_match(job, matches, RUBRIC)

        assert must_coverage == 0.0
        assert score.value == 55.0
        assert score.uncapped_value is not None
        assert score.uncapped_value > 55.0

    def test_the_cap_is_explained_in_plain_terms(self) -> None:
        job, matches = self._job_with(0.0)
        score, _, _ = score_job_match(job, matches, RUBRIC)
        assert score.cap_applied is not None
        assert "must-have" in score.cap_applied

    def test_partial_must_have_coverage_caps_less_severely(self) -> None:
        job, matches = self._job_with(0.6)
        score, must_coverage, _ = score_job_match(job, matches, RUBRIC)
        assert 0.5 <= must_coverage < 0.7
        assert score.value == 72.0

    def test_good_must_have_coverage_is_not_capped(self) -> None:
        job, matches = self._job_with(1.0)
        score, _, _ = score_job_match(job, matches, RUBRIC)
        assert score.cap_applied is None
        assert score.value == 100.0

    def test_a_job_with_no_must_haves_is_never_capped(self) -> None:
        nices = [requirement(f"Nice {i}", Priority.NICE) for i in range(3)]
        score, must_coverage, _ = score_job_match(
            JobTarget(requirements=nices),
            MatchReport(matches=[matched(n, 1.0) for n in nices]),
            RUBRIC,
        )
        assert must_coverage == 1.0
        assert score.cap_applied is None


class TestAtsScore:
    def test_a_clean_resume_scores_one_hundred(self) -> None:
        assert score_ats(AtsReport(), RUBRIC).value == 100.0

    def test_deductions_are_subtracted(self) -> None:
        report = AtsReport(
            findings=[
                AtsFinding(
                    rule_id=AtsRuleId.MULTI_COLUMN,
                    severity=AtsSeverity.CRITICAL,
                    deduction=15,
                    title="Multi-column",
                    detail="d",
                    fix="f",
                )
            ]
        )
        assert score_ats(report, RUBRIC).value == 85.0

    def test_the_score_never_goes_below_zero(self) -> None:
        findings = [
            AtsFinding(
                rule_id=AtsRuleId.MULTI_COLUMN,
                severity=AtsSeverity.CRITICAL,
                deduction=60,
                title="t",
                detail="d",
                fix="f",
            )
            for _ in range(5)
        ]
        assert score_ats(AtsReport(findings=findings), RUBRIC).value == 0.0

    def test_each_finding_becomes_a_negative_component(self) -> None:
        report = AtsReport(
            findings=[
                AtsFinding(
                    rule_id=AtsRuleId.HIDDEN_TEXT,
                    severity=AtsSeverity.CRITICAL,
                    deduction=20,
                    title="Hidden text",
                    detail="d",
                    fix="Remove it",
                )
            ]
        )
        component = score_ats(report, RUBRIC).components[0]
        assert component.contribution == -20
        assert component.detail == "Remove it"


class TestQualityScore:
    def test_good_writing_outscores_poor_writing(self) -> None:
        good = compute(
            job=JobTarget(),
            matches=MatchReport(),
            ats=AtsReport(),
            metrics=measure(good_document()),
        )
        poor = compute(
            job=JobTarget(),
            matches=MatchReport(),
            ats=AtsReport(),
            metrics=measure(poor_document()),
        )
        assert good.quality.value > poor.quality.value

    def test_a_missing_judgement_lowers_confidence_rather_than_inventing_one(self) -> None:
        report = compute(
            job=JobTarget(),
            matches=MatchReport(),
            ats=AtsReport(),
            metrics=measure(good_document()),
            judgement=None,
        )
        assert report.quality.confidence < 1.0
        assert report.quality.value > 0

    def test_a_judgement_contributes_to_the_score(self) -> None:
        metrics = measure(good_document())
        low = compute(
            job=JobTarget(),
            matches=MatchReport(),
            ats=AtsReport(),
            metrics=metrics,
            judgement=RubricJudgement(1, 1, 1, 1, 1),
        )
        high = compute(
            job=JobTarget(),
            matches=MatchReport(),
            ats=AtsReport(),
            metrics=metrics,
            judgement=RubricJudgement(5, 5, 5, 5, 5),
        )
        assert high.quality.value > low.quality.value

    def test_the_lowest_level_maps_to_zero_not_twenty(self) -> None:
        """A scale that cannot express "poor" is not a scale."""
        metrics = measure(ResumeDocument())
        report = compute(
            job=JobTarget(),
            matches=MatchReport(),
            ats=AtsReport(),
            metrics=metrics,
            judgement=RubricJudgement(1, 1, 1, 1, 1),
        )
        assert report.quality.value == 0.0


class TestOverallScore:
    def test_the_published_weights_are_applied(self) -> None:
        report = compute(
            job=JobTarget(),
            matches=MatchReport(),
            ats=AtsReport(),
            metrics=measure(ResumeDocument()),
            judgement=RubricJudgement(5, 5, 5, 5, 5),
        )
        expected = (
            report.job_match.value * 0.45 + report.quality.value * 0.35 + report.ats.value * 0.20
        )
        assert report.overall.value == pytest.approx(expected, abs=0.1)

    def test_each_part_appears_as_a_component(self) -> None:
        report = compute(
            job=JobTarget(),
            matches=MatchReport(),
            ats=AtsReport(),
            metrics=measure(ResumeDocument()),
        )
        keys = {component.key for component in report.overall.components}
        assert keys == {"job_match", "quality", "ats"}

    def test_a_poor_parse_lowers_confidence_everywhere(self) -> None:
        report = compute(
            job=JobTarget(),
            matches=MatchReport(),
            ats=AtsReport(),
            metrics=measure(good_document()),
            parse_confidence=0.4,
        )
        assert report.overall.confidence <= 0.4
        assert report.job_match.confidence <= 0.4


class TestBands:
    @pytest.mark.parametrize(
        ("value", "band"),
        [
            (92.0, Band.STRONG),
            (75.0, Band.COMPETITIVE),
            (60.0, Band.NEEDS_WORK),
            (45.0, Band.SIGNIFICANT_GAPS),
            (20.0, Band.NOT_ALIGNED),
        ],
    )
    def test_scores_land_in_the_right_band(self, value: float, band: Band) -> None:
        report = score_ats(
            AtsReport(
                findings=[
                    AtsFinding(
                        rule_id=AtsRuleId.MULTI_COLUMN,
                        severity=AtsSeverity.MINOR,
                        deduction=100 - value,
                        title="t",
                        detail="d",
                        fix="f",
                    )
                ]
            ),
            RUBRIC,
        )
        assert report.band is band


class TestExpectedBands:
    def test_a_band_is_produced_for_each_score(self) -> None:
        job = JobTarget(role_family="software_engineering", seniority=Seniority.ENTRY)
        report = compute(
            job=job, matches=MatchReport(), ats=AtsReport(), metrics=measure(good_document())
        )
        kinds = {band.kind for band in report.expected_bands}
        assert kinds == {ScoreKind.JOB_MATCH, ScoreKind.QUALITY, ScoreKind.ATS}

    def test_position_relative_to_the_range_is_reported(self) -> None:
        job = JobTarget(role_family="software_engineering", seniority=Seniority.ENTRY)
        report = compute(
            job=job, matches=MatchReport(), ats=AtsReport(), metrics=measure(good_document())
        )
        ats_band = next(b for b in report.expected_bands if b.kind is ScoreKind.ATS)
        assert ats_band.position == "above"  # a clean resume scores 100

    def test_an_unknown_role_family_falls_back(self) -> None:
        job = JobTarget(role_family="underwater_basket_weaving", seniority=Seniority.ENTRY)
        report = compute(
            job=job, matches=MatchReport(), ats=AtsReport(), metrics=measure(good_document())
        )
        assert report.expected_bands

    def test_percentiles_are_empty_without_cohort_data(self) -> None:
        """Inventing "top 20%" from no data would be dishonest."""
        report = compute(
            job=JobTarget(),
            matches=MatchReport(),
            ats=AtsReport(),
            metrics=measure(good_document()),
        )
        assert report.percentiles == []


class TestDeterminism:
    """The property the whole engine exists to guarantee."""

    def _report(self):
        reqs = [requirement("Python"), requirement("SQL", Priority.NICE)]
        return compute(
            job=JobTarget(requirements=reqs, role_family="software_engineering"),
            matches=MatchReport(matches=[matched(reqs[0], 1.0), matched(reqs[1], 0.5)]),
            ats=AtsReport(),
            metrics=measure(good_document()),
            judgement=RubricJudgement(4, 4, 3, 5, 4),
        )

    def test_the_same_inputs_give_the_same_numbers(self) -> None:
        first, second = self._report(), self._report()
        assert first.overall.value == second.overall.value
        assert first.job_match.value == second.job_match.value
        assert first.quality.value == second.quality.value
        assert first.ats.value == second.ats.value

    def test_repeated_runs_never_drift(self) -> None:
        values = {self._report().overall.value for _ in range(10)}
        assert len(values) == 1

    def test_the_rubric_version_is_stamped(self) -> None:
        assert self._report().rubric_version == RUBRIC["version"]


class TestExplainability:
    def test_every_score_can_be_expanded(self) -> None:
        reqs = [requirement("Python")]
        report = compute(
            job=JobTarget(requirements=reqs),
            matches=MatchReport(matches=[matched(reqs[0], 1.0)]),
            ats=AtsReport(),
            metrics=measure(good_document()),
            judgement=RubricJudgement(),
        )
        for score in report.as_dict().values():
            assert score.components

    def test_requirement_components_link_back_to_evidence(self) -> None:
        reqs = [requirement("Python")]
        report = compute(
            job=JobTarget(requirements=reqs),
            matches=MatchReport(matches=[matched(reqs[0], 1.0)]),
            ats=AtsReport(),
            metrics=measure(good_document()),
        )
        component = report.job_match.components[0]
        assert component.evidence_refs == [reqs[0].id]

    def test_every_component_records_how_it_was_produced(self) -> None:
        reqs = [requirement("Python")]
        report = compute(
            job=JobTarget(requirements=reqs),
            matches=MatchReport(matches=[matched(reqs[0], 1.0)]),
            ats=AtsReport(),
            metrics=measure(good_document()),
            judgement=RubricJudgement(),
        )
        for score in report.as_dict().values():
            for component in score.components:
                assert component.provenance in set(Provenance)

    def test_coverage_is_summarised_for_the_headline(self) -> None:
        reqs = [requirement("Python"), requirement("SQL"), requirement("Go")]
        summary = summarise_coverage(
            JobTarget(requirements=reqs),
            MatchReport(
                matches=[matched(reqs[0], 1.0), matched(reqs[1], 0.5), matched(reqs[2], 0.0)]
            ),
        )
        assert summary == {
            "matched": 1,
            "partial": 1,
            "missing": 1,
            "must_have_total": 3,
        }


class TestRubricJudge:
    def test_the_anchors_describe_every_level(self) -> None:
        for dimension in ("CLARITY", "IMPACT", "SPECIFICITY", "PROFESSIONALISM", "RELEVANCE"):
            assert dimension in ANCHORS
        for level in ("5", "4", "3", "2", "1"):
            assert f"  {level}  " in ANCHORS

    def test_the_prompt_carries_the_anchors(self) -> None:
        prompt = build_prompt("resume text")
        assert "CLARITY" in prompt
        assert "<resume>" in prompt

    def test_the_model_is_told_not_to_return_scores(self) -> None:
        """Weights live in rubric.yaml; a model that knew them could optimise
        against them."""
        assert "no percentages, scores or totals" in build_prompt("x")

    def test_protected_characteristics_are_ruled_out(self) -> None:
        prompt = build_prompt("x")
        assert "ethnicity" in prompt
        assert "Judge the writing" in prompt

    def test_embedded_instructions_are_declared_to_be_data(self) -> None:
        assert "not directions for you" in build_prompt("x")

    def test_levels_convert_into_a_judgement(self) -> None:
        judgement = to_judgement(
            LlmRubric(clarity=5, impact=2, specificity=4, professionalism=3, relevance=1)
        )
        assert judgement.clarity == 5
        assert judgement.impact == 2

    def test_the_resume_is_flattened_for_rating(self) -> None:
        text = describe(good_document())
        assert "EXPERIENCE" in text
        assert "40,000 requests" in text


class TestTheGateAppliesToOverallToo:
    """Capping job match alone left a hole.

    A well-written, cleanly formatted resume matching none of a role's
    essential requirements scored 75 overall and was labelled "Competitive" —
    the same misleading verdict the gate exists to prevent, arriving by a
    different route. Polish cannot substitute for being able to do the job.
    """

    def _report(self, must_strength: float):
        musts = [requirement(f"Must {i}", Priority.MUST) for i in range(2)]
        nices = [requirement(f"Nice {i}", Priority.NICE) for i in range(20)]
        return compute(
            job=JobTarget(requirements=musts + nices),
            matches=MatchReport(
                matches=[matched(m, must_strength) for m in musts]
                + [matched(n, 1.0) for n in nices]
            ),
            ats=AtsReport(),  # a flawless 100
            metrics=measure(good_document()),
            judgement=RubricJudgement(5, 5, 5, 5, 5),
        )

    def test_a_polished_resume_missing_every_must_have_is_not_competitive(self) -> None:
        report = self._report(0.0)
        assert report.ats.value == 100.0
        assert report.quality.value > 80
        assert report.overall.value == 55.0
        assert report.overall.band is not Band.COMPETITIVE

    def test_the_overall_cap_is_explained(self) -> None:
        report = self._report(0.0)
        assert report.overall.cap_applied is not None
        assert "must-have" in report.overall.cap_applied

    def test_the_uncapped_figure_is_preserved(self) -> None:
        """The user can still see what it would have been, and why it is not."""
        report = self._report(0.0)
        assert report.overall.uncapped_value is not None
        assert report.overall.uncapped_value > report.overall.value

    def test_meeting_the_must_haves_removes_the_cap(self) -> None:
        report = self._report(1.0)
        assert report.overall.cap_applied is None
        assert report.overall.value > 90
