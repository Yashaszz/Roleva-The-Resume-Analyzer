"""The matching cascade: does this resume satisfy this requirement?

Four tiers, cheapest first, stopping as soon as the answer is confident:

  1. **Canonical** — the taxonomy says these are the same skill.
  2. **Fuzzy** — typos and spacing differences.
  3. **Semantic** — embedding similarity, for wordings the taxonomy misses.
  4. **Adjudication** — one batched model call for the genuinely ambiguous.

Roughly three quarters of requirements are settled in the first two tiers at no
cost, which on a request-limited free tier is quota not spent.

The part that matters most is not *whether* a skill is present but **where**.
A skill demonstrated in a work bullet with an outcome is worth full credit; the
same skill sitting alone in a skills list is worth half. That single distinction
produces the observation no keyword matcher can make:

    "You list Docker in your skills section but never show using it."
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from roleva.matching.taxonomy import find_in_text, is_adjacent, normalise, resolve
from roleva.models.common import Provenance, SourceDoc, Span
from roleva.models.evidence import (
    ADJACENT_STRENGTH,
    Evidence,
    MatchReport,
    MatchStatus,
    RequirementMatch,
)
from roleva.models.job import JobTarget, Requirement, RequirementCategory
from roleva.models.resume import ResumeDocument, SkillOrigin
from roleva.parsing.dates import total_months
from roleva.parsing.spans import locate

#: Cosine similarity bands. Above the ceiling is a match, below the floor is
#: not, and only the band between them is worth a model call.
SEMANTIC_ACCEPT = 0.82
SEMANTIC_REJECT = 0.62

#: rapidfuzz score at or above which two strings name the same thing.
#: See taxonomy.FUZZY_THRESHOLD for how this value was measured.
FUZZY_ACCEPT = 82

#: A quantified requirement met at or above this share of the stated figure is
#: "close" rather than absent — someone with 2 of 3 years has not failed.
QUANTIFIER_CLOSE = 0.6
QUANTIFIER_CLOSE_STRENGTH = 0.6
QUANTIFIER_SHORT_STRENGTH = 0.3


@dataclass
class ResumeIndex:
    """Everything about a resume that matching needs, built once.

    Each skill mention is recorded with where it was found, because location is
    what decides the strength of the evidence.
    """

    text: str
    #: canonical skill -> the strongest origin it appears in, and its span.
    skills: dict[str, tuple[SkillOrigin, Span]] = field(default_factory=dict)
    #: Every canonical skill found anywhere, for the unmatched-content report.
    all_canonical: set[str] = field(default_factory=set)
    experience_months: int = 0
    #: canonical skill -> months of experience in contexts mentioning it.
    months_by_skill: dict[str, int] = field(default_factory=dict)


#: Which origin beats which, when a skill appears in several places. The
#: strongest wins: a skill both listed and demonstrated is demonstrated.
_ORIGIN_RANK = {
    SkillOrigin.EXPERIENCE_BULLET: 6,
    SkillOrigin.PROJECT_BULLET: 5,
    SkillOrigin.CERTIFICATION: 4,
    SkillOrigin.SUMMARY: 3,
    SkillOrigin.SKILLS_LIST: 2,
    SkillOrigin.EDUCATION: 2,
    SkillOrigin.OTHER: 1,
}


def _record(index: ResumeIndex, canonical: str, origin: SkillOrigin, span: Span) -> None:
    index.all_canonical.add(canonical)
    existing = index.skills.get(canonical)
    if existing is None or _ORIGIN_RANK[origin] > _ORIGIN_RANK[existing[0]]:
        index.skills[canonical] = (origin, span)


def build_index(document: ResumeDocument, text: str) -> ResumeIndex:
    """Index a resume by skill and by where each skill appears."""
    index = ResumeIndex(text=text)

    # Bullets first: they are the strongest evidence, and recording them before
    # the skills list means a demonstrated skill is never downgraded to a
    # listed one.
    for origin, bullet in document.all_bullets():
        for canonical, _, _ in find_in_text(bullet.text):
            span = bullet.span or locate(text, bullet.text)
            if span is not None:
                _record(index, canonical, origin, span)

    for item in document.experience:
        months = item.dates.months or 0
        for bullet in item.bullets:
            for canonical, _, _ in find_in_text(bullet.text):
                index.months_by_skill[canonical] = index.months_by_skill.get(canonical, 0) + months

    for mention in document.skills:
        resolution = resolve(mention.raw)
        canonical = resolution.canonical if resolution else mention.raw
        if mention.span is not None:
            _record(index, canonical, mention.origin, mention.span)

    for credential in document.certifications:
        for canonical, _, _ in find_in_text(credential.title):
            if credential.span is not None:
                _record(index, canonical, SkillOrigin.CERTIFICATION, credential.span)

    index.experience_months = total_months([item.dates for item in document.experience])
    return index


def _evidence(origin: SkillOrigin, span: Span, provenance: Provenance, note: str) -> Evidence:
    return Evidence(span=span, origin=origin, provenance=provenance, note=note)


def _tier_canonical(requirement: Requirement, index: ResumeIndex) -> Evidence | None:
    """Tier 1: the taxonomy says these are the same skill."""
    resolution = resolve(requirement.canonical or requirement.text)
    if resolution is None:
        return None

    found = index.skills.get(resolution.canonical)
    if found is None:
        return None

    origin, span = found
    return _evidence(origin, span, Provenance.LEXICAL, f"matched as {resolution.canonical}")


def _tier_fuzzy(requirement: Requirement, index: ResumeIndex) -> Evidence | None:
    """Tier 2: close enough to be the same thing despite spelling."""
    target = normalise(requirement.canonical or requirement.text)
    if len(target) < 3:
        return None

    # Two skills the taxonomy already knows are never fuzzy-matched to each
    # other. "Flask" and "Slack" are similar strings and different tools, and
    # confusing them would credit a skill the candidate does not have. So when
    # the requirement resolves exactly, only its own canonical form is eligible.
    resolution = resolve(requirement.canonical or requirement.text)
    only_canonical = resolution.canonical if resolution is not None and resolution.exact else None

    best: tuple[str, float] | None = None
    for canonical in index.skills:
        if only_canonical is not None and canonical != only_canonical:
            continue
        score = fuzz.token_sort_ratio(target, normalise(canonical))
        if score >= FUZZY_ACCEPT and (best is None or score > best[1]):
            best = (canonical, score)

    if best is None:
        return None

    origin, span = index.skills[best[0]]
    return _evidence(origin, span, Provenance.LEXICAL, f"matched as {best[0]}")


def _tier_adjacent(requirement: Requirement, index: ResumeIndex) -> Evidence | None:
    """Partial credit for a related but different skill.

    Deliberately not a match. Telling someone they satisfy a React requirement
    because they know Vue is a claim they might act on, and it would be false.
    """
    resolution = resolve(requirement.canonical or requirement.text)
    if resolution is None:
        return None

    for canonical in index.skills:
        if is_adjacent(resolution.canonical, canonical):
            origin, span = index.skills[canonical]
            return _evidence(
                origin,
                span,
                Provenance.SEMANTIC,
                f"{canonical} is related to {resolution.canonical}, but not the same",
            )
    return None


def _tier_literal(requirement: Requirement, index: ResumeIndex) -> Evidence | None:
    """Fallback for requirements the taxonomy does not know.

    Soft skills and responsibilities are phrased too freely for a lexicon, so
    the requirement's own wording is looked for directly.
    """
    if requirement.category in {RequirementCategory.HARD_SKILL, RequirementCategory.TOOL}:
        return None

    text = requirement.text.strip()
    if len(text) < 4:
        return None

    span = locate(index.text, text, doc=SourceDoc.RESUME)
    if span is None:
        return None

    return _evidence(SkillOrigin.OTHER, span, Provenance.LEXICAL, "wording found in the resume")


def _resolve_quantifier(
    requirement: Requirement, index: ResumeIndex, strength: float
) -> tuple[float, int | None, str | None]:
    """Apply a years-of-experience requirement to an otherwise matched skill.

    Months are computed from parsed employment dates, never estimated, and the
    result adjusts strength rather than replacing it: someone with two of three
    years has partial credit, not none.
    """
    if requirement.quantifier is None or requirement.quantifier.years is None:
        return strength, None, None

    required_months = int(requirement.quantifier.years * 12)
    resolution = resolve(requirement.canonical or requirement.text)
    canonical = resolution.canonical if resolution else None

    observed = index.months_by_skill.get(canonical or "", 0) if canonical else 0
    observed = max(observed, 0)

    if observed >= required_months:
        return strength, observed, None

    ratio = observed / required_months if required_months else 0.0
    if ratio >= QUANTIFIER_CLOSE:
        return (
            min(strength, QUANTIFIER_CLOSE_STRENGTH),
            observed,
            f"close: about {observed // 12} of {int(requirement.quantifier.years)} years",
        )

    return (
        min(strength, QUANTIFIER_SHORT_STRENGTH),
        observed,
        f"significant gap: {requirement.quantifier.years} years required",
    )


def match_requirement(requirement: Requirement, index: ResumeIndex) -> RequirementMatch:
    """Run one requirement through the cascade."""
    evidence = (
        _tier_canonical(requirement, index)
        or _tier_fuzzy(requirement, index)
        or _tier_literal(requirement, index)
    )

    if evidence is not None:
        strength = evidence.strength
        strength, observed, note = _resolve_quantifier(requirement, index, strength)

        # Half credit or less is a partial match, not a pass. This is what
        # turns "Docker is in your skills list" into a finding rather than a
        # tick.
        status = MatchStatus.MATCHED if strength > 0.5 else MatchStatus.PARTIAL

        explanation = note or _explain(evidence)
        return RequirementMatch(
            requirement_id=requirement.id,
            status=status,
            strength=round(strength, 3),
            evidence=[evidence],
            observed_months=observed,
            explanation=explanation,
        )

    adjacent = _tier_adjacent(requirement, index)
    if adjacent is not None:
        return RequirementMatch(
            requirement_id=requirement.id,
            status=MatchStatus.PARTIAL,
            strength=ADJACENT_STRENGTH,
            evidence=[adjacent],
            is_adjacent=True,
            explanation=adjacent.note,
        )

    return RequirementMatch(
        requirement_id=requirement.id,
        status=MatchStatus.MISSING,
        strength=0.0,
        explanation="Not found anywhere in the resume",
    )


def _explain(evidence: Evidence) -> str:
    """Say what the evidence is worth, and why."""
    if evidence.origin is SkillOrigin.SKILLS_LIST:
        return (
            "Listed in your skills section, but not shown in use. Demonstrated "
            "experience counts for more."
        )
    if evidence.origin is SkillOrigin.EXPERIENCE_BULLET:
        return "Demonstrated in your work experience"
    if evidence.origin is SkillOrigin.PROJECT_BULLET:
        return "Demonstrated in a project"
    if evidence.origin is SkillOrigin.CERTIFICATION:
        return "Backed by a certification"
    return "Found in your resume"


def unmatched_resume_skills(index: ResumeIndex, job: JobTarget) -> list[str]:
    """Skills the resume has that this job did not ask for.

    Useful in its own right: it shows what to trim for this particular
    application, which is the other half of tailoring a resume.
    """
    wanted = set()
    for requirement in job.requirements:
        resolution = resolve(requirement.canonical or requirement.text)
        if resolution is not None:
            wanted.add(resolution.canonical)

    return sorted(index.all_canonical - wanted)


def match_all(job: JobTarget, index: ResumeIndex) -> MatchReport:
    """Run every requirement through the cascade."""
    matches = [match_requirement(requirement, index) for requirement in job.requirements]

    return MatchReport(
        matches=matches,
        unmatched_resume_skills=unmatched_resume_skills(index, job),
        llm_adjudicated_count=0,
    )


def needs_adjudication(job: JobTarget, report: MatchReport) -> list[Requirement]:
    """Requirements the deterministic tiers could not settle.

    These are the only ones worth a model call, and they all go in one batched
    request. Adjudicating each separately would exhaust a per-minute quota on
    its own.
    """
    by_id = {match.requirement_id: match for match in report.matches}
    return [
        requirement
        for requirement in job.requirements
        if by_id.get(requirement.id)
        and by_id[requirement.id].status is MatchStatus.MISSING
        and requirement.category
        not in {RequirementCategory.EDUCATION, RequirementCategory.CERTIFICATION}
    ]
