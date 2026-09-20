"""What a shared report is allowed to contain.

A share link hands somebody else a document built out of the owner's resume.
That is the most sensitive thing this product does, so the rule is simple and
absolute: **redaction happens here, on the server, before the report is
serialised.** Nothing is hidden with CSS, nothing is filtered in the browser.
A person who opens devtools on a shared page finds exactly what a person who
reads the JSON finds, because they are the same bytes.

Three modes, in increasing order of exposure:

* ``scores_only`` — the numbers and the verdict. No resume text at all: no
  quotes, no bullets, no skills, no employers. Safe to post in public.
* ``full_redacted`` — the whole report with the owner's identity removed. The
  default, because most people sharing a report want feedback on the analysis
  rather than to introduce themselves.
* ``full_identified`` — everything, exactly as the owner sees it. Only ever
  chosen deliberately.

The redaction is subtractive, never a mask over data that is still present.
Fields are replaced or emptied, so there is nothing left to leak.
"""

from __future__ import annotations

import re
from enum import StrEnum

from roleva.models.report import AnalysisReport
from roleva.models.resume import ContactInfo


class Visibility(StrEnum):
    SCORES_ONLY = "scores_only"
    FULL_REDACTED = "full_redacted"
    FULL_IDENTIFIED = "full_identified"


#: What a redacted field is replaced with. Readable rather than a black box:
#: "[name removed]" tells the reader something was there, which is honest, and
#: stops a reader wondering whether the resume simply had no name.
REMOVED = "[removed]"
REMOVED_NAME = "[name removed]"
REMOVED_ORG = "[employer removed]"


def apply(report: AnalysisReport, visibility: Visibility) -> AnalysisReport:
    """Return a copy of the report safe to show under this visibility.

    Always a copy. Mutating the caller's report would mean a cached analysis
    could be served redacted to its own owner, which is the kind of bug that
    only shows up after somebody shares something.
    """
    if visibility is Visibility.FULL_IDENTIFIED:
        return report.model_copy(deep=True)

    shared = report.model_copy(deep=True)

    if visibility is Visibility.SCORES_ONLY:
        # Identity first, then content. The first version stripped content only
        # and left the name in the headline, the verdict and the recommendation
        # titles — which made the *most* restrictive mode the leakiest one.
        return _scores_only(_redact_identity(shared))

    return _redact_identity(shared)


def _scores_only(report: AnalysisReport) -> AnalysisReport:
    """Strip everything derived from the resume, keeping the analysis of it.

    The requirements survive because they are the employer's words from a public
    posting, not the candidate's. The evidence does not, because every piece of
    it is a verbatim line from the resume.
    """
    from roleva.models.resume import ResumeDocument

    report.resume = ResumeDocument()

    for match in report.matches.matches:
        # The strength and the status are the analysis; the quote is the resume.
        match.evidence = []
        match.explanation = None
    report.matches.unmatched_resume_skills = []

    # Bullet suggestions quote the original line in full, so they go entirely.
    report.bullet_suggestions = []
    # Section feedback describes the writing rather than quoting it, but it can
    # name an employer in an example. Not worth the risk at this level.
    report.section_feedback = []

    # Recommendations can quote a resume line in their detail text.
    report.recommendations = [
        rec.model_copy(update={"detail": _strip_quotes(rec.detail)})
        for rec in report.recommendations
    ]

    report.strengths = []
    report.weaknesses = []

    return report


def _redact_identity(report: AnalysisReport) -> AnalysisReport:
    """Remove who the person is, keep what they wrote.

    The hard part is that a name appears in more places than the contact block:
    in bullet text ("Led the Raghavendra pilot"), in an employer field, in an
    evidence quote. So the identifying strings are collected first and then
    removed from every piece of free text in the document.
    """
    contact = report.resume.contact
    secrets = _identifying_strings(contact, report)

    report.resume.contact = ContactInfo(
        name=REMOVED_NAME if contact.name else None,
        email=REMOVED if contact.email else None,
        phone=REMOVED if contact.phone else None,
        # Location is kept: "Bengaluru" is useful context for a reader judging a
        # match and does not identify anybody on its own.
        location=contact.location,
        links=[REMOVED for _ in contact.links],
    )

    for item in report.resume.experience:
        item.organization = REMOVED_ORG if item.organization else None
        for bullet in item.bullets:
            bullet.text = _scrub(bullet.text, secrets)

    for project in report.resume.projects:
        for bullet in project.bullets:
            bullet.text = _scrub(bullet.text, secrets)

    for education in report.resume.education:
        # An institution is identifying in combination with a graduation year,
        # and it is rarely what a reader is judging.
        education.institution = REMOVED_ORG if education.institution else None

    if report.resume.summary:
        report.resume.summary.text = _scrub(report.resume.summary.text, secrets)

    # Evidence quotes are verbatim resume lines: they need the same treatment.
    for match in report.matches.matches:
        for evidence in match.evidence:
            evidence.span.text = _scrub(evidence.span.text, secrets)
        if match.explanation:
            match.explanation = _scrub(match.explanation, secrets)

    report.bullet_suggestions = [
        suggestion.model_copy(
            update={
                "original": _scrub(suggestion.original, secrets),
                "suggestion": _scrub(suggestion.suggestion, secrets),
            }
        )
        for suggestion in report.bullet_suggestions
    ]

    report.verdict = _scrub(report.verdict, secrets)
    report.headline = _scrub(report.headline, secrets)
    report.strengths = [_scrub(item, secrets) for item in report.strengths]
    report.weaknesses = [_scrub(item, secrets) for item in report.weaknesses]
    report.recommendations = [
        rec.model_copy(
            update={
                "title": _scrub(rec.title, secrets),
                "detail": _scrub(rec.detail, secrets),
            }
        )
        for rec in report.recommendations
    ]

    return report


def _identifying_strings(contact: ContactInfo, report: AnalysisReport) -> list[str]:
    """Every string that would identify this person, longest first.

    Name parts are included individually because a resume that says "Aditi
    Raghavendra" at the top often says "Aditi" further down. Two characters or
    fewer are skipped: removing every "Li" from a document destroys it.

    Employers and institutions are collected too. Clearing the `organization`
    field is not enough, because the same name turns up in bullet text, in an
    evidence quote and — the case that caught this — in a recommendation title
    generated from the analysis.
    """
    found: list[str] = []

    for item in report.resume.experience:
        if item.organization:
            found.append(item.organization)
    for education in report.resume.education:
        if education.institution:
            found.append(education.institution)

    if contact.name:
        found.append(contact.name)
        found.extend(part for part in contact.name.split() if len(part) > 2)
    if contact.email:
        found.append(contact.email)
        # The local part often appears alone, as a username.
        local = contact.email.split("@")[0]
        if len(local) > 3:
            found.append(local)
    if contact.phone:
        found.append(contact.phone)
    found.extend(link for link in contact.links if len(link) > 3)

    # Longest first, so "Aditi Raghavendra" is removed before "Aditi" can
    # fragment it into "[name removed] Raghavendra".
    return sorted({s.strip() for s in found if s and len(s.strip()) > 2}, key=len, reverse=True)


def _scrub(text: str, secrets: list[str]) -> str:
    """Remove every identifying string from a piece of free text."""
    if not text:
        return text

    for secret in secrets:
        # Case-insensitive, word-bounded where the string is word-like, so
        # "Raghavendra" in a sentence goes but "raghavendra" inside a longer
        # token is not half-eaten.
        pattern = re.escape(secret)
        if secret[0].isalnum() and secret[-1].isalnum():
            pattern = rf"\b{pattern}\b"
        text = re.sub(pattern, REMOVED_NAME, text, flags=re.IGNORECASE)

    return text


_QUOTED = re.compile(r"[“\"][^”\"]{10,}[”\"]")


def _strip_quotes(text: str) -> str:
    """Remove quoted resume lines from otherwise safe prose.

    Recommendations are generated from computed facts, but several of them quote
    the line they are about. At `scores_only` that quote is the one thing that
    must not travel.
    """
    return _QUOTED.sub("[quote removed]", text)


def describe(visibility: Visibility) -> str:
    """One sentence for the UI, so the owner knows what they are handing over."""
    return {
        Visibility.SCORES_ONLY: (
            "Scores and the verdict only. No part of your resume is included."
        ),
        Visibility.FULL_REDACTED: (
            "The whole report with your name, contact details and employers removed."
        ),
        Visibility.FULL_IDENTIFIED: (
            "The complete report, exactly as you see it, including your name and employers."
        ),
    }[visibility]
