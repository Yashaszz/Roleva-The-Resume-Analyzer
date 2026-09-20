"""The deterministic advice engine: selection, projected gain, recommendations, verdict.

The property these tests protect is that **no number here is invented**. A
projected gain is a measured difference between two runs of the scoring engine,
and the verdict only ever repeats values the engine produced.
"""

from __future__ import annotations

from roleva.advice import recommendations as recs
from roleva.advice import summary as verdict
from roleva.advice.impact import (
    MIN_MEANINGFUL_GAIN,
    ScoringInputs,
    project_all_ats,
    project_ats_fix,
    project_metric_fix,
    project_requirement,
)
from roleva.advice.selection import (
    MAX_SELECTED,
    describe_for_prompt,
    select_weak_bullets,
)
from roleva.models.ats import AtsFinding, AtsReport, AtsRuleId, AtsSeverity
from roleva.models.common import SourceDoc, Span
from roleva.models.evidence import Evidence, MatchReport, MatchStatus, RequirementMatch
from roleva.models.job import JobTarget, Priority, Requirement, RequirementCategory, Seniority
from roleva.models.report import Severity
from roleva.models.resume import Bullet, ExperienceItem, ResumeDocument, SkillOrigin
from roleva.quality.metrics import measure
from roleva.quality.proofread import proofread
from roleva.scoring.engine import RubricJudgement

# --------------------------------------------------------------------- setup ---


def _req(text: str, priority: Priority = Priority.MUST) -> Requirement:
    return Requirement(text=text, category=RequirementCategory.HARD_SKILL, priority=priority)


def _match(
    req: Requirement, strength: float, origin: SkillOrigin | None = None
) -> RequirementMatch:
    evidence = []
    if origin is not None:
        evidence = [
            Evidence(
                span=Span(doc=SourceDoc.RESUME, start=0, end=6, text="Python"),
                origin=origin,
                provenance="lexical",  # type: ignore[arg-type]
            )
        ]
    return RequirementMatch(
        requirement_id=req.id,
        status=(
            MatchStatus.MISSING
            if strength == 0
            else MatchStatus.MATCHED
            if strength > 0.5
            else MatchStatus.PARTIAL
        ),
        strength=strength,
        evidence=evidence,
    )


def _resume(*bullets: str) -> ResumeDocument:
    return ResumeDocument(
        experience=[
            ExperienceItem(
                title="Software Engineering Intern",
                organization="Zentara Technologies",
                bullets=[Bullet(text=text) for text in bullets],
            )
        ]
    )


STRONG_BULLETS = (
    "Built a Django service handling 40,000 requests per day",
    "Reduced p95 latency from 820ms to 210ms by adding indexes",
    "Wrote 60 unit tests, raising coverage from 34% to 81%",
)

WEAK_BULLETS = (
    "Responsible for the company website",
    "Worked on various tasks as needed",
    "Was involved in the migration project",
)


def _inputs(
    *,
    strengths: list[float],
    bullets: tuple[str, ...] = STRONG_BULLETS,
    findings: list[AtsFinding] | None = None,
    priorities: list[Priority] | None = None,
) -> ScoringInputs:
    priorities = priorities or [Priority.MUST] * len(strengths)
    requirements = [_req(f"Skill {i}", p) for i, p in enumerate(priorities)]
    return ScoringInputs(
        job=JobTarget(
            requirements=requirements,
            role_family="software_engineering",
            seniority=Seniority.ENTRY,
        ),
        matches=MatchReport(
            matches=[_match(r, s) for r, s in zip(requirements, strengths, strict=True)]
        ),
        ats=AtsReport(findings=findings or [], checks_run=15),
        metrics=measure(_resume(*bullets)),
        judgement=RubricJudgement(4, 4, 4, 4, 4),
    )


def _finding(rule: AtsRuleId, deduction: float) -> AtsFinding:
    return AtsFinding(
        rule_id=rule,
        severity=AtsSeverity.MAJOR,
        deduction=deduction,
        title=f"Fix {rule.value}",
        detail="Detected in the document.",
        fix="Remove it.",
    )


# ------------------------------------------------------------------ selection ---


class TestWeakBulletSelection:
    def test_weak_bullets_are_selected(self) -> None:
        selected = select_weak_bullets(_resume(*WEAK_BULLETS))
        assert {bullet.text for bullet in selected} == set(WEAK_BULLETS)

    def test_strong_bullets_are_left_alone(self) -> None:
        assert select_weak_bullets(_resume(*STRONG_BULLETS)) == []

    def test_every_selection_carries_its_reasons(self) -> None:
        for bullet in select_weak_bullets(_resume(*WEAK_BULLETS)):
            assert bullet.reasons
            assert all(reason.strip() for reason in bullet.reasons)

    def test_the_worst_bullet_comes_first(self) -> None:
        selected = select_weak_bullets(
            _resume(
                "Built a Django service handling 40,000 requests per day",
                "Helped with testing",
                "Worked on the site",
            )
        )
        assert selected[0].score >= selected[-1].score

    def test_the_list_is_capped(self) -> None:
        many = _resume(*[f"Worked on project {i}" for i in range(20)])
        assert len(select_weak_bullets(many)) <= MAX_SELECTED

    def test_selection_is_deterministic(self) -> None:
        document = _resume(*WEAK_BULLETS, *STRONG_BULLETS)
        first = [(b.bullet_id, b.score) for b in select_weak_bullets(document)]
        for _ in range(9):
            assert [(b.bullet_id, b.score) for b in select_weak_bullets(document)] == first

    def test_the_prompt_list_hides_ids(self) -> None:
        """The model answers by index, so it cannot attach a rewrite to a made-up id."""
        selected = select_weak_bullets(_resume(*WEAK_BULLETS))
        rendered = describe_for_prompt(selected)
        for bullet in selected:
            assert bullet.bullet_id not in rendered
            assert bullet.text in rendered

    def test_empty_documents_are_handled(self) -> None:
        assert select_weak_bullets(ResumeDocument()) == []


# --------------------------------------------------------------------- impact ---


class TestProjectedGain:
    def test_matching_a_missing_requirement_raises_the_score(self) -> None:
        inputs = _inputs(strengths=[0.0, 1.0, 1.0])
        target = inputs.job.requirements[0].id
        projection = project_requirement(inputs, target)
        assert projection.gain > 0
        assert projection.to_value > projection.from_value

    def test_the_gain_is_the_measured_difference(self) -> None:
        """Not an estimate: re-score the hypothetical and check it matches."""
        inputs = _inputs(strengths=[0.0, 1.0])
        baseline = inputs.score()
        projection = project_requirement(inputs, inputs.job.requirements[0].id)

        hypothetical = inputs.copy()
        hypothetical.matches.matches[0].strength = 1.0
        hypothetical.matches.matches[0].status = MatchStatus.MATCHED

        assert projection.to_value == hypothetical.score().overall.value
        assert projection.from_value == baseline.overall.value

    def test_projection_never_mutates_the_real_analysis(self) -> None:
        inputs = _inputs(strengths=[0.0, 1.0])
        before = inputs.score().overall.value
        project_requirement(inputs, inputs.job.requirements[0].id)
        project_ats_fix(inputs, AtsRuleId.MULTI_COLUMN)
        project_metric_fix(inputs, "quantification")
        assert inputs.score().overall.value == before
        assert inputs.matches.matches[0].strength == 0.0

    def test_lifting_the_must_have_cap_is_worth_more_than_its_weight(self) -> None:
        """The gate makes one requirement disproportionately valuable, correctly."""
        gated = _inputs(strengths=[0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
        assert gated.score().overall.cap_applied is not None
        gain = project_requirement(gated, gated.job.requirements[0].id).gain

        ungated = _inputs(strengths=[1.0, 1.0, 1.0, 1.0, 1.0, 0.0])
        assert ungated.score().overall.cap_applied is None
        smaller = project_requirement(ungated, ungated.job.requirements[5].id).gain

        assert gain > smaller

    def test_an_already_matched_requirement_is_worth_nothing(self) -> None:
        inputs = _inputs(strengths=[1.0, 1.0])
        assert project_requirement(inputs, inputs.job.requirements[0].id).gain == 0.0

    def test_an_unknown_requirement_is_worth_nothing(self) -> None:
        inputs = _inputs(strengths=[1.0])
        assert project_requirement(inputs, "does-not-exist").gain == 0.0

    def test_removing_an_ats_finding_raises_the_score(self) -> None:
        inputs = _inputs(strengths=[1.0], findings=[_finding(AtsRuleId.MULTI_COLUMN, 15)])
        assert project_ats_fix(inputs, AtsRuleId.MULTI_COLUMN).gain > 0

    def test_a_clean_document_has_nothing_to_gain_from_formatting(self) -> None:
        inputs = _inputs(strengths=[1.0])
        assert project_all_ats(inputs).gain == 0.0

    def test_a_metric_already_at_target_is_worth_nothing(self) -> None:
        inputs = _inputs(strengths=[1.0], bullets=STRONG_BULLETS)
        metric = inputs.metrics.get("quantification")
        assert metric is not None and metric.meets_target
        assert project_metric_fix(inputs, "quantification").gain == 0.0

    def test_a_failing_metric_is_worth_something(self) -> None:
        inputs = _inputs(strengths=[1.0], bullets=WEAK_BULLETS)
        assert project_metric_fix(inputs, "quantification").gain > 0

    def test_projection_is_deterministic(self) -> None:
        inputs = _inputs(strengths=[0.0, 1.0])
        target = inputs.job.requirements[0].id
        values = {project_requirement(inputs, target).gain for _ in range(10)}
        assert len(values) == 1


# ------------------------------------------------------------ recommendations ---


class TestRecommendations:
    def test_a_missing_must_have_is_recommended_first(self) -> None:
        inputs = _inputs(strengths=[0.0, 1.0, 1.0, 1.0])
        built = recs.build(inputs)
        assert built
        assert built[0].severity is Severity.HIGH
        assert inputs.job.requirements[0].id in built[0].related_requirement_ids

    def test_recommendations_are_ranked_by_measured_gain(self) -> None:
        inputs = _inputs(
            strengths=[0.0, 0.5, 1.0],
            bullets=WEAK_BULLETS,
            findings=[_finding(AtsRuleId.MULTI_COLUMN, 15)],
        )
        gains = [r.projected_gain for r in recs.build(inputs)]
        assert gains == sorted(gains, reverse=True)

    def test_a_perfect_analysis_produces_no_recommendations(self) -> None:
        inputs = _inputs(strengths=[1.0, 1.0], bullets=STRONG_BULLETS)
        assert recs.build(inputs) == []

    def test_the_list_is_capped(self) -> None:
        inputs = _inputs(
            strengths=[0.0] * 12,
            bullets=WEAK_BULLETS,
            findings=[
                _finding(AtsRuleId.MULTI_COLUMN, 15),
                _finding(AtsRuleId.TEXT_IN_TABLE, 12),
            ],
        )
        built = recs.build(inputs)
        assert len(built) <= recs.MAX_RECOMMENDATIONS
        assert 5 <= recs.MAX_RECOMMENDATIONS <= 7

    def test_nothing_trivial_is_recommended(self) -> None:
        inputs = _inputs(strengths=[0.0] + [1.0] * 30, bullets=WEAK_BULLETS)
        for recommendation in recs.build(inputs):
            assert (
                recommendation.projected_gain >= MIN_MEANINGFUL_GAIN
                or recommendation.id == "writing:proofread"
            )

    def test_duplicates_are_removed(self) -> None:
        inputs = _inputs(strengths=[0.0, 0.0], bullets=WEAK_BULLETS)
        built = recs.build(inputs)
        assert len({r.id for r in built}) == len(built)
        assert len({r.title.lower() for r in built}) == len(built)

    def test_one_ats_recommendation_per_rule(self) -> None:
        inputs = _inputs(
            strengths=[1.0],
            findings=[
                _finding(AtsRuleId.MULTI_COLUMN, 15),
                _finding(AtsRuleId.MULTI_COLUMN, 15),
            ],
        )
        ats_ids = [r.id for r in recs.build(inputs) if r.id.startswith("ats:")]
        assert len(ats_ids) == len(set(ats_ids))

    def test_listed_but_not_demonstrated_gets_its_own_advice(self) -> None:
        requirement = _req("Docker")
        inputs = ScoringInputs(
            job=JobTarget(
                requirements=[requirement, _req("Python")],
                role_family="software_engineering",
                seniority=Seniority.ENTRY,
            ),
            matches=MatchReport(
                matches=[
                    _match(requirement, 0.5, SkillOrigin.SKILLS_LIST),
                    _match(_req("Python"), 1.0),
                ]
            ),
            ats=AtsReport(checks_run=15),
            metrics=measure(_resume(*STRONG_BULLETS)),
            judgement=RubricJudgement(4, 4, 4, 4, 4),
        )
        titles = [r.title for r in recs.build(inputs)]
        assert any("Show where you used Docker" in title for title in titles)

    def test_spelling_advice_claims_no_score_gain(self) -> None:
        """Spelling is not scored, so it must not pretend to be worth points."""
        inputs = _inputs(strengths=[1.0], bullets=STRONG_BULLETS)
        report = proofread(_resume("Recieved an award for the seperate migration"))
        built = recs.build(inputs, proofread_report=report)
        spelling = next(r for r in built if r.id == "writing:proofread")
        assert spelling.projected_gain == 0.0
        assert "do not affect your score" in spelling.detail

    def test_recommendations_are_deterministic(self) -> None:
        inputs = _inputs(
            strengths=[0.0, 0.5, 1.0],
            bullets=WEAK_BULLETS,
            findings=[_finding(AtsRuleId.MULTI_COLUMN, 15)],
        )
        first = [(r.id, r.projected_gain) for r in recs.build(inputs)]
        for _ in range(9):
            assert [(r.id, r.projected_gain) for r in recs.build(inputs)] == first

    def test_total_gain_is_the_sum(self) -> None:
        inputs = _inputs(strengths=[0.0, 0.0, 1.0], bullets=WEAK_BULLETS)
        built = recs.build(inputs)
        assert recs.total_available_gain(built) == round(sum(r.projected_gain for r in built), 1)


# -------------------------------------------------------------------- verdict ---


class TestVerdict:
    def _facts(self, inputs: ScoringInputs) -> verdict.Facts:
        return verdict.facts(scores=inputs.score(), job=inputs.job, matches=inputs.matches)

    def test_the_verdict_states_the_score_and_the_band(self) -> None:
        inputs = _inputs(strengths=[1.0, 1.0])
        data = self._facts(inputs)
        text = verdict.build(data)
        assert f"{data.overall:g}" in text
        assert data.band_label in text

    def test_every_number_in_the_verdict_is_a_computed_one(self) -> None:
        """The anti-hallucination property, asserted directly."""
        import re

        inputs = _inputs(
            strengths=[0.0, 0.5, 1.0],
            bullets=WEAK_BULLETS,
            findings=[_finding(AtsRuleId.MULTI_COLUMN, 15)],
        )
        data = self._facts(inputs)
        text = verdict.build(data)

        # Requirement names are quoted verbatim from the job description. A
        # digit inside one is the employer's text, not a claim the verdict is
        # making, so those quotes are removed before the numbers are checked.
        for quoted in data.top_gaps + data.listed_not_shown:
            text = text.replace(quoted, "")

        permitted = data.numbers()
        for token in re.findall(r"\d+(?:\.\d+)?", text):
            assert float(token) in permitted, f"{token} is not a computed value"

    def test_a_capped_score_says_so(self) -> None:
        inputs = _inputs(strengths=[0.0, 0.0, 0.0, 1.0])
        data = self._facts(inputs)
        assert data.capped
        assert "capped" in verdict.build(data).lower()

    def test_missing_must_haves_are_named(self) -> None:
        inputs = _inputs(strengths=[0.0, 1.0])
        text = verdict.build(self._facts(inputs))
        assert inputs.job.requirements[0].text in text

    def test_strengths_are_not_invented_for_a_weak_resume(self) -> None:
        inputs = _inputs(
            strengths=[0.0, 0.0],
            bullets=WEAK_BULLETS,
            findings=[_finding(AtsRuleId.MULTI_COLUMN, 25)],
        )
        data = self._facts(inputs)
        assert verdict.strengths(data) == []

    def test_a_strong_resume_gets_factual_strengths(self) -> None:
        inputs = _inputs(strengths=[1.0, 1.0], bullets=STRONG_BULLETS)
        assert verdict.strengths(self._facts(inputs))

    def test_weaknesses_are_specific(self) -> None:
        inputs = _inputs(strengths=[0.0, 0.0], bullets=WEAK_BULLETS)
        assert any("no evidence" in item for item in verdict.weaknesses(self._facts(inputs)))

    def test_the_verdict_is_deterministic(self) -> None:
        inputs = _inputs(strengths=[0.0, 0.5, 1.0], bullets=WEAK_BULLETS)
        data = self._facts(inputs)
        assert len({verdict.build(data) for _ in range(10)}) == 1

    def test_it_survives_an_empty_job(self) -> None:
        inputs = ScoringInputs(
            job=JobTarget(role_family="general", seniority=Seniority.ENTRY),
            matches=MatchReport(),
            ats=AtsReport(checks_run=15),
            metrics=measure(_resume(*STRONG_BULLETS)),
        )
        assert verdict.build(self._facts(inputs))


class TestHeadline:
    """The sentence the report opens with, at display size."""

    def _facts(self, inputs: ScoringInputs) -> verdict.Facts:
        return verdict.facts(scores=inputs.score(), job=inputs.job, matches=inputs.matches)

    def test_it_states_the_essential_coverage(self) -> None:
        inputs = _inputs(strengths=[1.0, 1.0, 0.0, 0.0, 0.0])
        assert verdict.headline(self._facts(inputs)) == (
            "You show 2 of the 5 things this job calls essential."
        )

    def test_full_coverage_reads_naturally(self) -> None:
        """ "all 3 of the 3" is what a template writes; a person would not."""
        inputs = _inputs(strengths=[1.0, 1.0, 1.0])
        assert verdict.headline(self._facts(inputs)) == (
            "You show all 3 things this job calls essential."
        )

    def test_it_is_one_sentence(self) -> None:
        """A headline is set at 46px. Two sentences there is a wall."""
        for strengths in ([1.0, 0.0], [1.0, 1.0], [0.0, 0.0, 0.0]):
            text = verdict.headline(self._facts(_inputs(strengths=strengths)))
            assert text.count(".") == 1, text

    def test_a_posting_with_no_essentials_still_gets_one(self) -> None:
        inputs = _inputs(strengths=[1.0, 0.0], priorities=[Priority.NICE, Priority.NICE])
        text = verdict.headline(self._facts(inputs))
        assert text.strip()
        assert text.count(".") == 1

    def test_it_never_flatters_a_failing_resume(self) -> None:
        """No encouraging fallback: a resume matching nothing is told so."""
        inputs = _inputs(strengths=[0.0, 0.0, 0.0])
        text = verdict.headline(self._facts(inputs))
        assert "0 of the 3" in text

    def test_it_is_deterministic(self) -> None:
        data = self._facts(_inputs(strengths=[1.0, 0.0, 0.5]))
        assert len({verdict.headline(data) for _ in range(10)}) == 1
