"""Parse confidence.

Roleva can be wrong about a resume, and the honest response is to say so rather
than present a confident report built on a bad parse. This score decides
whether the UI shows results plainly, shows them with a caveat, or marks them
provisional.

It is computed from evidence already gathered during parsing, so it costs
nothing extra — and, importantly, it is not a guess about quality. Each
component measures something specific that went right or wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from roleva.models.resume import ResumeDocument, SectionKind
from roleva.parsing.contact import completeness
from roleva.parsing.pdf_reader import ExtractedDocument
from roleva.parsing.sectionizer import SectionReport

#: Above this, results are shown without qualification.
HIGH_CONFIDENCE = 0.8

#: Below this, scores are marked provisional and the user is told why.
LOW_CONFIDENCE = 0.5


@dataclass
class ConfidenceBreakdown:
    """The components behind the score, so a poor parse can be explained to the
    user rather than merely flagged."""

    text_density: float
    section_detection: float
    contact_completeness: float
    span_verification: float
    content_present: float

    #: Relative weights. Section detection dominates: if the sections are wrong,
    #: everything downstream is attributed to the wrong place.
    WEIGHTS: ClassVar[dict[str, float]] = {
        "text_density": 0.15,
        "section_detection": 0.30,
        "contact_completeness": 0.15,
        "span_verification": 0.25,
        "content_present": 0.15,
    }

    @property
    def score(self) -> float:
        total = (
            self.text_density * self.WEIGHTS["text_density"]
            + self.section_detection * self.WEIGHTS["section_detection"]
            + self.contact_completeness * self.WEIGHTS["contact_completeness"]
            + self.span_verification * self.WEIGHTS["span_verification"]
            + self.content_present * self.WEIGHTS["content_present"]
        )
        return round(min(1.0, max(0.0, total)), 3)

    @property
    def weakest(self) -> str:
        """The component that dragged the score down, for the user-facing
        explanation."""
        values = {
            "text_density": self.text_density,
            "section_detection": self.section_detection,
            "contact_completeness": self.contact_completeness,
            "span_verification": self.span_verification,
            "content_present": self.content_present,
        }
        return min(values, key=lambda key: values[key])


#: Sections a resume is expected to have. Projects counts toward the same slot
#: as experience, because a student with neither is genuinely unusual but one
#: with only projects is not.
_EXPECTED = (
    {SectionKind.EXPERIENCE, SectionKind.PROJECTS},
    {SectionKind.EDUCATION},
    {SectionKind.SKILLS},
    {SectionKind.CONTACT},
)


def _section_score(sections: SectionReport) -> float:
    if not sections.sections:
        return 0.0
    found = sum(1 for group in _EXPECTED if sections.kinds & group)
    coverage = found / len(_EXPECTED)

    confidences = [s.confidence for s in sections.sections if s.kind is not SectionKind.OTHER]
    quality = sum(confidences) / len(confidences) if confidences else 0.0

    return round(0.6 * coverage + 0.4 * quality, 3)


def _density_score(extracted: ExtractedDocument) -> float:
    """Text per page, against a healthy band.

    Too little suggests extraction failed; the upper end is not penalised here
    because density is a quality issue, not a parsing one.
    """
    if extracted.page_count == 0:
        return 0.0
    per_page = len(extracted.text) / extracted.page_count
    return round(min(1.0, per_page / 900), 3)


def _content_score(document: ResumeDocument) -> float:
    """Whether structuring actually produced content.

    A document that parsed but yielded no bullets and no skills has failed in a
    way the other components would not notice.
    """
    bullets = sum(len(item.bullets) for item in document.experience)
    bullets += sum(len(project.bullets) for project in document.projects)
    has_history = bool(document.experience or document.projects or document.education)

    signals = [
        min(1.0, bullets / 6),
        1.0 if document.skills else 0.0,
        1.0 if has_history else 0.0,
    ]
    return round(sum(signals) / len(signals), 3)


def assess(
    *,
    extracted: ExtractedDocument,
    sections: SectionReport,
    document: ResumeDocument,
    unverified_count: int,
    reported_count: int,
) -> ConfidenceBreakdown:
    """Score how much this parse can be trusted.

    `unverified_count` is how many model-reported items could not be found in
    the resume. A high proportion means the model was improvising, which is the
    strongest available signal that the structured output is unreliable.
    """
    verification = 1.0
    if reported_count > 0:
        verification = round(1.0 - (unverified_count / reported_count), 3)

    return ConfidenceBreakdown(
        text_density=_density_score(extracted),
        section_detection=_section_score(sections),
        contact_completeness=round(completeness(document.contact), 3),
        span_verification=max(0.0, verification),
        content_present=_content_score(document),
    )


def explain(breakdown: ConfidenceBreakdown) -> str | None:
    """A sentence for the user when confidence is not high.

    Names what went wrong and what to do about it. Returns None when there is
    nothing worth saying.
    """
    if breakdown.score >= HIGH_CONFIDENCE:
        return None

    reasons = {
        "text_density": (
            "We could only read a little text from this PDF. If it was exported "
            "from a design tool, try exporting again as a text-based PDF."
        ),
        "section_detection": (
            "We had trouble identifying this resume's sections. Standard headings "
            "like Experience, Education and Skills help both us and most ATS systems."
        ),
        "contact_completeness": (
            "We couldn't find complete contact details near the top of your resume."
        ),
        "span_verification": (
            "Parts of this resume were hard to read reliably, so some details may be incomplete."
        ),
        "content_present": (
            "We found very little content to analyse. If your resume has more on it, "
            "the PDF may not have exported cleanly."
        ),
    }

    prefix = (
        "Results are provisional. "
        if breakdown.score < LOW_CONFIDENCE
        else "Some results may be less precise. "
    )
    return prefix + reasons[breakdown.weakest]
