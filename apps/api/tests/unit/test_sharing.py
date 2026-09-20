"""Share links, redaction and the percentile floor.

Gate 8 asks for three things, and all three are asserted here rather than
described: redaction happens server-side, a revoked link is gone immediately,
and a percentile cannot render below thirty samples.

The redaction tests work by serialising the shared report and searching the
JSON for the owner's name. That is the only check that means anything — a field
that still holds the name but is not rendered has not been redacted, it has been
hidden, and the difference is one view-source away.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

from roleva.models.common import SourceDoc, Span
from roleva.models.evidence import Evidence, MatchReport, MatchStatus, RequirementMatch
from roleva.models.job import JobTarget, Priority, Requirement, RequirementCategory
from roleva.models.report import (
    AnalysisReport,
    AnalysisStatus,
    BulletSuggestion,
    Recommendation,
    Severity,
)
from roleva.models.resume import (
    Bullet,
    ContactInfo,
    EducationItem,
    ExperienceItem,
    ResumeDocument,
    SkillOrigin,
)
from roleva.models.scoring import Band, Score, ScoreKind, ScoreReport
from roleva.sharing import links, redaction
from roleva.sharing.percentiles import MINIMUM_SAMPLE, _position
from roleva.sharing.redaction import Visibility

MIGRATIONS = Path(__file__).parents[3].parent / "supabase" / "migrations"

NAME = "Aditi Raghavendra"
EMAIL = "aditi.r@example.com"
EMPLOYER = "Zentara Technologies"


def _report() -> AnalysisReport:
    """A report carrying the owner's identity in every place it can appear."""
    requirement = Requirement(
        text="Python", category=RequirementCategory.HARD_SKILL, priority=Priority.MUST
    )
    quote = f"Built a Django service at {EMPLOYER} with {NAME.split()[0]}"

    def score(kind: ScoreKind) -> Score:
        return Score(kind=kind, value=61.0, band=Band.NEEDS_WORK)

    return AnalysisReport(
        id="a1",
        status=AnalysisStatus.COMPLETE,
        created_at=datetime.now(UTC),
        resume=ResumeDocument(
            contact=ContactInfo(
                name=NAME,
                email=EMAIL,
                phone="+91 98765 43210",
                location="Bengaluru",
                links=["github.com/aditir"],
            ),
            summary=Bullet(text=f"{NAME} is a backend engineer."),
            experience=[
                ExperienceItem(
                    title="Engineer",
                    organization=EMPLOYER,
                    bullets=[Bullet(text=quote)],
                )
            ],
            education=[EducationItem(institution="Anna University", degree="BE")],
        ),
        job=JobTarget(requirements=[requirement], role_family="backend_engineering"),
        matches=MatchReport(
            matches=[
                RequirementMatch(
                    requirement_id=requirement.id,
                    status=MatchStatus.MATCHED,
                    strength=1.0,
                    explanation=f"Found in work at {EMPLOYER}",
                    evidence=[
                        Evidence(
                            span=Span(doc=SourceDoc.RESUME, start=0, end=len(quote), text=quote),
                            origin=SkillOrigin.EXPERIENCE_BULLET,
                            provenance="lexical",  # type: ignore[arg-type]
                        )
                    ],
                )
            ]
        ),
        ats={},  # type: ignore[arg-type]
        scores=ScoreReport(
            overall=score(ScoreKind.OVERALL),
            job_match=score(ScoreKind.JOB_MATCH),
            ats=score(ScoreKind.ATS),
            quality=score(ScoreKind.QUALITY),
            must_coverage=1.0,
            overall_coverage=1.0,
            rubric_version="1.0.0",
        ),
        headline=f"{NAME} shows 1 of the 1 things this job calls essential.",
        verdict=f"{NAME} matches this role well.",
        strengths=[f"{NAME} quantifies outcomes."],
        weaknesses=[f"Work at {EMPLOYER} is thinly described."],
        bullet_suggestions=[
            BulletSuggestion(
                bullet_id="b1",
                original=quote,
                suggestion=f"Rebuilt the service at {EMPLOYER}",
                section="experience",  # type: ignore[arg-type]
            )
        ],
        recommendations=[
            Recommendation(
                id="r1",
                title=f"Show more of the work at {EMPLOYER}",
                detail=f"Your line “{quote}” could say what changed.",
                severity=Severity.MEDIUM,
            )
        ],
        rubric_version="1.0.0",
        prompt_version="p1",
    )


def _json(report: AnalysisReport) -> str:
    return json.dumps(report.model_dump(mode="json"))


class TestRedactionIsServerSide:
    """The Gate 8 criterion: the name is not in the bytes, not merely unrendered."""

    def test_full_redacted_removes_the_name_everywhere(self) -> None:
        shared = redaction.apply(_report(), Visibility.FULL_REDACTED)
        body = _json(shared)
        assert NAME not in body
        assert "Raghavendra" not in body
        assert "Aditi" not in body

    def test_full_redacted_removes_contact_details(self) -> None:
        shared = redaction.apply(_report(), Visibility.FULL_REDACTED)
        body = _json(shared)
        assert EMAIL not in body
        assert "98765" not in body
        assert "github.com/aditir" not in body

    def test_full_redacted_removes_employers(self) -> None:
        shared = redaction.apply(_report(), Visibility.FULL_REDACTED)
        assert EMPLOYER not in _json(shared)

    def test_full_redacted_keeps_the_analysis(self) -> None:
        """Redaction must not gut the thing being shared."""
        shared = redaction.apply(_report(), Visibility.FULL_REDACTED)
        assert shared.scores.overall.value == 61.0
        assert len(shared.matches.matches) == 1
        assert shared.matches.matches[0].strength == 1.0
        assert shared.job.requirements[0].text == "Python"

    def test_location_survives(self) -> None:
        """A city is context a reader needs and does not identify anybody."""
        shared = redaction.apply(_report(), Visibility.FULL_REDACTED)
        assert shared.resume.contact.location == "Bengaluru"

    def test_scores_only_carries_no_resume_text_at_all(self) -> None:
        shared = redaction.apply(_report(), Visibility.SCORES_ONLY)
        body = _json(shared)
        assert NAME not in body
        assert EMPLOYER not in body
        assert "Django" not in body
        assert shared.bullet_suggestions == []
        assert shared.matches.matches[0].evidence == []

    def test_scores_only_keeps_the_numbers(self) -> None:
        shared = redaction.apply(_report(), Visibility.SCORES_ONLY)
        assert shared.scores.overall.value == 61.0
        assert shared.matches.matches[0].strength == 1.0

    def test_scores_only_strips_quotes_from_recommendations(self) -> None:
        shared = redaction.apply(_report(), Visibility.SCORES_ONLY)
        assert "Built a Django service" not in _json(shared)

    def test_full_identified_changes_nothing(self) -> None:
        original = _report()
        shared = redaction.apply(original, Visibility.FULL_IDENTIFIED)
        assert _json(shared) == _json(original)

    def test_the_original_is_never_mutated(self) -> None:
        """A cached analysis must not be served redacted to its own owner."""
        original = _report()
        redaction.apply(original, Visibility.FULL_REDACTED)
        redaction.apply(original, Visibility.SCORES_ONLY)
        assert original.resume.contact.name == NAME
        assert NAME in _json(original)

    def test_a_longer_name_is_removed_before_its_parts(self) -> None:
        """Otherwise "Aditi Raghavendra" becomes "[name removed] Raghavendra"."""
        shared = redaction.apply(_report(), Visibility.FULL_REDACTED)
        assert "Raghavendra" not in _json(shared)

    def test_every_mode_is_covered(self) -> None:
        """A new visibility mode must not default to showing everything."""
        for mode in Visibility:
            shared = redaction.apply(_report(), mode)
            if mode is not Visibility.FULL_IDENTIFIED:
                assert NAME not in _json(shared), mode


class TestTokens:
    def test_tokens_are_long_and_unguessable(self) -> None:
        token = links.new_token()
        # 32 bytes base64url-encoded is 43 characters.
        assert len(token) >= 43
        assert re.fullmatch(r"[A-Za-z0-9_-]+", token)

    def test_tokens_do_not_repeat(self) -> None:
        assert len({links.new_token() for _ in range(500)}) == 500


class TestExpiry:
    def test_the_default_is_seven_days(self) -> None:
        expires = links._clamp_expiry(None)
        assert 6 < (expires - datetime.now(UTC)).days < 8

    def test_it_is_capped_at_thirty_days(self) -> None:
        """Clamped rather than rejected: a month is a better answer than an error."""
        expires = links._clamp_expiry(365)
        assert (expires - datetime.now(UTC)).days <= links.MAX_EXPIRY_DAYS

    def test_zero_becomes_one_day(self) -> None:
        expires = links._clamp_expiry(0)
        assert expires > datetime.now(UTC)


class TestActiveness:
    def _link(self, **overrides) -> links.ShareLink:
        base = dict(
            token="t",
            analysis_id="a",
            visibility=Visibility.FULL_REDACTED,
            expires_at=datetime.now(UTC) + timedelta(days=1),
            view_count=0,
            revoked=False,
        )
        base.update(overrides)
        return links.ShareLink(**base)  # type: ignore[arg-type]

    def test_a_fresh_link_is_active(self) -> None:
        assert self._link().active

    def test_a_revoked_link_is_not(self) -> None:
        assert not self._link(revoked=True).active

    def test_an_expired_link_is_not(self) -> None:
        assert not self._link(expires_at=datetime.now(UTC) - timedelta(seconds=1)).active


class TestPercentileFloor:
    """Gate 8: a percentile must not render below thirty samples."""

    def test_the_floor_is_enforced_in_sql(self) -> None:
        """In SQL, so a frontend bug cannot render what was never sent."""
        sql = (MIGRATIONS / "0003_sharing_and_cohorts.sql").read_text(encoding="utf-8")
        assert "having count(*) >= 30" in sql.lower()

    def test_the_python_constant_matches_the_migration(self) -> None:
        sql = (MIGRATIONS / "0003_sharing_and_cohorts.sql").read_text(encoding="utf-8")
        assert f">= {MINIMUM_SAMPLE}" in sql

    def test_a_thin_cohort_is_dropped_when_it_falls_below(self) -> None:
        """A cohort that shrinks must stop being reported, not go stale."""
        sql = (MIGRATIONS / "0003_sharing_and_cohorts.sql").read_text(encoding="utf-8")
        assert "delete from public.cohort_stats" in sql.lower()


class TestPercentilePosition:
    ROW: ClassVar[dict[str, float]] = {
        "p10": 40.0,
        "p25": 50.0,
        "p50": 60.0,
        "p75": 70.0,
        "p90": 80.0,
    }

    def test_the_median_is_the_fiftieth(self) -> None:
        assert _position(60.0, self.ROW) == 50.0

    def test_it_interpolates_between_quantiles(self) -> None:
        """Snapping would claim "75th" for everything from 60 to 70."""
        assert 50.0 < _position(65.0, self.ROW) < 75.0

    def test_below_the_tenth_is_reported_as_ten(self) -> None:
        """The five stored quantiles say nothing about the tail below p10."""
        assert _position(5.0, self.ROW) == 10.0

    def test_above_the_ninetieth_is_reported_as_ninety(self) -> None:
        assert _position(99.0, self.ROW) == 90.0

    def test_it_is_monotonic(self) -> None:
        values = [_position(v, self.ROW) for v in range(30, 95, 5)]
        assert values == sorted(values)


class TestVisibilityCopy:
    def test_every_mode_has_a_sentence_for_the_owner(self) -> None:
        """Somebody choosing a mode has to know what they are handing over."""
        for mode in Visibility:
            text = redaction.describe(mode)
            assert text.strip()
            assert text.endswith(".")
