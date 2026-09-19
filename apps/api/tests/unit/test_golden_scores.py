"""Golden score tests.

These pin exact scores for fixed inputs. They exist to make rubric changes
*visible*: adjust a weight and this file fails, showing precisely which scores
moved and by how much. Updating the expected values is then a deliberate act
recorded in the diff, rather than a silent shift nobody notices until a user
asks why their score changed.

A failure here is not necessarily a bug. It means the scoring changed, and the
diff should say why.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roleva.models.ats import AtsFinding, AtsReport, AtsRuleId, AtsSeverity
from roleva.models.evidence import MatchReport, MatchStatus, RequirementMatch
from roleva.models.job import JobTarget, Priority, Requirement, RequirementCategory, Seniority
from roleva.models.resume import Bullet, DateRange, ExperienceItem, ResumeDocument
from roleva.quality.metrics import measure
from roleva.scoring.engine import RubricJudgement, compute, load_rubric

GOLDEN_PATH = Path(__file__).parents[1] / "golden" / "scores.json"


def _requirement(text: str, priority: Priority) -> Requirement:
    return Requirement(text=text, category=RequirementCategory.HARD_SKILL, priority=priority)


def _match(req: Requirement, strength: float) -> RequirementMatch:
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
        evidence=[],
    )


def _finding(rule: AtsRuleId, deduction: float) -> AtsFinding:
    return AtsFinding(
        rule_id=rule,
        severity=AtsSeverity.MAJOR,
        deduction=deduction,
        title=rule.value,
        detail="fixed for the golden case",
        fix="fixed for the golden case",
    )


def _strong_resume() -> ResumeDocument:
    return ResumeDocument(
        experience=[
            ExperienceItem(
                title="Software Engineering Intern",
                organization="Zentara Technologies",
                dates=DateRange(start_year=2024, start_month=6, end_year=2025, end_month=6),
                bullets=[
                    Bullet(text="Built a Django service handling 40,000 requests per day"),
                    Bullet(text="Reduced p95 latency from 820ms to 210ms by adding indexes"),
                    Bullet(text="Wrote 60 unit tests, raising coverage from 34% to 81%"),
                    Bullet(text="Mentored 2 interns through their first deployment"),
                ],
            )
        ]
    )


def _weak_resume() -> ResumeDocument:
    return ResumeDocument(
        experience=[
            ExperienceItem(
                title="Intern",
                bullets=[
                    Bullet(text="Responsible for the company website"),
                    Bullet(text="Worked on various tasks as needed"),
                    Bullet(text="I helped with testing and other duties"),
                    Bullet(text="Was involved in the migration project"),
                ],
            )
        ]
    )


def _case_strong_candidate() -> dict[str, float]:
    """Everything matched, clean formatting, well-written."""
    musts = [_requirement(f"Must {i}", Priority.MUST) for i in range(3)]
    nices = [_requirement(f"Nice {i}", Priority.NICE) for i in range(2)]
    report = compute(
        job=JobTarget(
            requirements=musts + nices,
            role_family="software_engineering",
            seniority=Seniority.ENTRY,
        ),
        matches=MatchReport(matches=[_match(r, 1.0) for r in musts + nices]),
        ats=AtsReport(checks_run=15),
        metrics=measure(_strong_resume()),
        judgement=RubricJudgement(4, 4, 4, 5, 4),
    )
    return _snapshot(report)


def _case_missing_must_haves() -> dict[str, float]:
    """The case the must-have gate exists for."""
    musts = [_requirement(f"Must {i}", Priority.MUST) for i in range(2)]
    nices = [_requirement(f"Nice {i}", Priority.NICE) for i in range(20)]
    report = compute(
        job=JobTarget(
            requirements=musts + nices,
            role_family="software_engineering",
            seniority=Seniority.ENTRY,
        ),
        matches=MatchReport(
            matches=[_match(m, 0.0) for m in musts] + [_match(n, 1.0) for n in nices]
        ),
        ats=AtsReport(checks_run=15),
        metrics=measure(_strong_resume()),
        judgement=RubricJudgement(4, 4, 4, 4, 4),
    )
    return _snapshot(report)


def _case_listed_not_demonstrated() -> dict[str, float]:
    """Every skill present but only in a skills list — all partial credit."""
    musts = [_requirement(f"Must {i}", Priority.MUST) for i in range(4)]
    report = compute(
        job=JobTarget(
            requirements=musts,
            role_family="software_engineering",
            seniority=Seniority.ENTRY,
        ),
        matches=MatchReport(matches=[_match(m, 0.5) for m in musts]),
        ats=AtsReport(checks_run=15),
        metrics=measure(_strong_resume()),
        judgement=RubricJudgement(3, 3, 3, 4, 3),
    )
    return _snapshot(report)


def _case_poor_formatting() -> dict[str, float]:
    """Good content, badly formatted."""
    musts = [_requirement(f"Must {i}", Priority.MUST) for i in range(3)]
    report = compute(
        job=JobTarget(
            requirements=musts,
            role_family="software_engineering",
            seniority=Seniority.ENTRY,
        ),
        matches=MatchReport(matches=[_match(m, 1.0) for m in musts]),
        ats=AtsReport(
            findings=[
                _finding(AtsRuleId.MULTI_COLUMN, 15),
                _finding(AtsRuleId.TEXT_IN_TABLE, 12),
                _finding(AtsRuleId.CONTENT_IN_HEADER_FOOTER, 10),
            ],
            checks_run=15,
        ),
        metrics=measure(_strong_resume()),
        judgement=RubricJudgement(4, 4, 4, 4, 4),
    )
    return _snapshot(report)


def _case_weak_writing() -> dict[str, float]:
    """Matched on skills, but the writing carries none of it."""
    musts = [_requirement(f"Must {i}", Priority.MUST) for i in range(3)]
    report = compute(
        job=JobTarget(
            requirements=musts,
            role_family="software_engineering",
            seniority=Seniority.ENTRY,
        ),
        matches=MatchReport(matches=[_match(m, 1.0) for m in musts]),
        ats=AtsReport(checks_run=15),
        metrics=measure(_weak_resume()),
        judgement=RubricJudgement(2, 1, 2, 3, 2),
    )
    return _snapshot(report)


def _case_no_judgement() -> dict[str, float]:
    """The rubric call failed; scoring proceeds on counted metrics alone."""
    musts = [_requirement("Must 0", Priority.MUST)]
    report = compute(
        job=JobTarget(requirements=musts, role_family="general", seniority=Seniority.ENTRY),
        matches=MatchReport(matches=[_match(musts[0], 1.0)]),
        ats=AtsReport(checks_run=15),
        metrics=measure(_strong_resume()),
        judgement=None,
    )
    return _snapshot(report)


CASES = {
    "strong_candidate": _case_strong_candidate,
    "missing_must_haves": _case_missing_must_haves,
    "listed_not_demonstrated": _case_listed_not_demonstrated,
    "poor_formatting": _case_poor_formatting,
    "weak_writing": _case_weak_writing,
    "no_judgement": _case_no_judgement,
}


def _snapshot(report) -> dict[str, float]:
    return {
        "overall": report.overall.value,
        "job_match": report.job_match.value,
        "quality": report.quality.value,
        "ats": report.ats.value,
        "must_coverage": report.must_coverage,
        "rubric_version": report.rubric_version,
    }


def _current() -> dict[str, dict[str, float]]:
    return {name: case() for name, case in CASES.items()}


@pytest.fixture(scope="module")
def golden() -> dict[str, dict[str, float]]:
    if not GOLDEN_PATH.exists():
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(json.dumps(_current(), indent=2, sort_keys=True) + "\n")
    data: dict[str, dict[str, float]] = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return data


class TestGoldenScores:
    @pytest.mark.parametrize("name", sorted(CASES))
    def test_scores_match_the_recorded_values(
        self, name: str, golden: dict[str, dict[str, float]]
    ) -> None:
        """If this fails, the scoring changed.

        That may be entirely intended — but the new numbers must be committed
        deliberately, so the change is visible to whoever reads the diff.
        """
        assert name in golden, f"No golden values for {name}; delete scores.json to regenerate"
        assert CASES[name]() == golden[name]

    def test_every_case_is_recorded(self, golden: dict[str, dict[str, float]]) -> None:
        assert set(golden) == set(CASES)

    def test_the_rubric_version_is_pinned(self, golden: dict[str, dict[str, float]]) -> None:
        """A rubric version bump should show up here rather than silently."""
        current = load_rubric()["version"]
        for values in golden.values():
            assert values["rubric_version"] == current


class TestGoldenCasesAreMeaningful:
    """The snapshots are only worth pinning if they differ from each other."""

    def test_the_cases_produce_different_scores(self) -> None:
        overalls = {name: case()["overall"] for name, case in CASES.items()}
        assert len(set(overalls.values())) >= 5

    def test_the_gate_case_is_actually_capped(self) -> None:
        assert _case_missing_must_haves()["job_match"] == 55.0

    def test_demonstrated_beats_listed(self) -> None:
        assert _case_strong_candidate()["job_match"] > _case_listed_not_demonstrated()["job_match"]

    def test_formatting_only_affects_the_ats_score(self) -> None:
        clean = _case_strong_candidate()
        messy = _case_poor_formatting()
        assert messy["ats"] < clean["ats"]
        assert messy["job_match"] == clean["job_match"]

    def test_weak_writing_lowers_quality_but_not_matching(self) -> None:
        strong = _case_strong_candidate()
        weak = _case_weak_writing()
        assert weak["quality"] < strong["quality"]
        assert weak["job_match"] == strong["job_match"]
