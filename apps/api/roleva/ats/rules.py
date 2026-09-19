"""ATS checks — entirely deterministic.

No model touches this stage. Every check here is a measurable fact about the
document: how it is laid out, which fonts it uses, whether an email address is
present. That makes the ATS score reproducible by construction, and it means
each finding can say exactly where the problem is.

Every finding carries four things, because a deduction the user cannot act on
is just a number that makes them feel bad:

    what is wrong · where it is · why it matters · how to fix it

The deductions are published in docs/SCORING.md. They are judgement calls about
relative severity, not measurements, and saying so is part of being honest
about the score.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from roleva.ats.signals import AtsSignals
from roleva.models.ats import AtsFinding, AtsReport, AtsRuleId, AtsSeverity
from roleva.models.resume import ResumeDocument, SectionKind
from roleva.parsing.pdf_reader import ExtractedDocument
from roleva.parsing.sectionizer import SectionReport
from roleva.parsing.validators import PdfStats, filename_is_professional

#: A resume longer than this, for someone early in their career, is padded.
_PAGE_LIMIT_ENTRY_LEVEL = 2

#: Below this share of dates parsed, the date formats are a problem rather than
#: an occasional oddity.
_DATE_PARSE_FLOOR = 0.6


@dataclass
class AtsContext:
    """Everything the checks need, gathered once."""

    extracted: ExtractedDocument
    signals: AtsSignals
    sections: SectionReport
    document: ResumeDocument
    stats: PdfStats
    filename: str | None = None


Check = Callable[[AtsContext], AtsFinding | None]

_REGISTRY: list[Check] = []


def check(func: Check) -> Check:
    """Register a check. Order of registration is order of reporting."""
    _REGISTRY.append(func)
    return func


# ---------------------------------------------------------------- layout ---


@check
def multi_column(context: AtsContext) -> AtsFinding | None:
    pages = context.extracted.multi_column_pages
    if not pages:
        return None
    return AtsFinding(
        rule_id=AtsRuleId.MULTI_COLUMN,
        severity=AtsSeverity.CRITICAL,
        deduction=15,
        title="Multi-column layout",
        detail=(
            f"Your resume uses more than one column on "
            f"{'page ' + str(pages[0]) if len(pages) == 1 else f'{len(pages)} pages'}. "
            "Many applicant tracking systems read straight across the page, which "
            "interleaves the columns and scrambles the text."
        ),
        fix="Use a single-column layout. It looks plainer, and it survives parsing.",
        page=pages[0],
        occurrences=len(pages),
    )


@check
def text_in_table(context: AtsContext) -> AtsFinding | None:
    pages = context.signals.table_pages
    if not pages:
        return None
    return AtsFinding(
        rule_id=AtsRuleId.TEXT_IN_TABLE,
        severity=AtsSeverity.MAJOR,
        deduction=12,
        title="Content inside a table",
        detail=(
            "Part of your resume is laid out as a table. Many parsers read table "
            "cells in storage order rather than visual order, so dates and roles "
            "can end up separated from each other."
        ),
        fix="Replace the table with plain paragraphs and bullet points.",
        page=pages[0],
        occurrences=len(pages),
    )


@check
def text_as_image(context: AtsContext) -> AtsFinding | None:
    pages = context.signals.large_image_pages
    if not pages:
        return None
    return AtsFinding(
        rule_id=AtsRuleId.TEXT_AS_IMAGE,
        severity=AtsSeverity.CRITICAL,
        deduction=25,
        title="Large image on the page",
        detail=(
            "A large image covers part of your resume. Any text inside an image is "
            "invisible to automated screening — it cannot be read, matched or "
            "searched."
        ),
        fix="Make sure every word is real text rather than part of a graphic.",
        page=pages[0],
        occurrences=len(pages),
    )


@check
def content_in_header_footer(context: AtsContext) -> AtsFinding | None:
    margins = context.signals.margin_texts
    if not margins:
        return None

    sample = margins[0][1][:60]
    return AtsFinding(
        rule_id=AtsRuleId.CONTENT_IN_HEADER_FOOTER,
        severity=AtsSeverity.MAJOR,
        deduction=10,
        title="Content in the page margin",
        detail=(
            f'Text sits in the header or footer area — for example "{sample}". '
            "Many parsers read only the main body of the page and never see it. "
            "Contact details placed there are a common reason applications go "
            "unanswered."
        ),
        fix="Move anything important into the main body of the page.",
        page=margins[0][0],
        occurrences=len(margins),
    )


@check
def informative_graphics(context: AtsContext) -> AtsFinding | None:
    """Skill bars, rating dots and progress rings convey nothing to a parser."""
    if not context.signals.large_image_pages and context.stats.image_count < 3:
        return None
    if context.signals.large_image_pages:
        return None  # already reported, and more severely, as text-as-image

    return AtsFinding(
        rule_id=AtsRuleId.INFORMATIVE_GRAPHICS,
        severity=AtsSeverity.MINOR,
        deduction=5,
        title="Graphics used to convey information",
        detail=(
            f"This resume contains {context.stats.image_count} images. Skill bars, "
            "rating dots and similar graphics carry no meaning to automated "
            "screening — a five-star Python rating reads as nothing at all."
        ),
        fix="State proficiency in words, in context: where you used it and what you built.",
    )


# --------------------------------------------------------------- structure ---


@check
def no_standard_sections(context: AtsContext) -> AtsFinding | None:
    recognised = context.sections.kinds - {SectionKind.OTHER, SectionKind.CONTACT}
    if recognised:
        return None
    return AtsFinding(
        rule_id=AtsRuleId.NO_STANDARD_SECTIONS,
        severity=AtsSeverity.CRITICAL,
        deduction=12,
        title="No recognisable section headings",
        detail=(
            "We could not identify standard sections in this resume. Automated "
            "screening relies on headings to know which text is your experience "
            "and which is your education."
        ),
        fix='Use plain headings: "Experience", "Education", "Skills", "Projects".',
    )


@check
def missing_experience(context: AtsContext) -> AtsFinding | None:
    kinds = context.sections.kinds
    if SectionKind.EXPERIENCE in kinds or SectionKind.PROJECTS in kinds:
        return None
    return AtsFinding(
        rule_id=AtsRuleId.MISSING_EXPERIENCE,
        severity=AtsSeverity.MAJOR,
        deduction=8,
        title="No experience or projects section",
        detail=(
            "We found neither an experience section nor a projects section. One of "
            "the two is what most screening looks for first."
        ),
        fix="Add a Projects section if you have no work history yet. Coursework counts.",
    )


@check
def missing_education(context: AtsContext) -> AtsFinding | None:
    if SectionKind.EDUCATION in context.sections.kinds:
        return None
    return AtsFinding(
        rule_id=AtsRuleId.MISSING_EDUCATION,
        severity=AtsSeverity.MAJOR,
        deduction=8,
        title="No education section",
        detail=(
            "We could not find an education section. Many filters for entry-level "
            "roles check for a degree field specifically."
        ),
        fix='Add an "Education" heading with your degree, institution and year.',
    )


# ----------------------------------------------------------------- contact ---


@check
def missing_email(context: AtsContext) -> AtsFinding | None:
    if context.document.contact.email:
        return None
    return AtsFinding(
        rule_id=AtsRuleId.MISSING_EMAIL,
        severity=AtsSeverity.CRITICAL,
        deduction=10,
        title="No email address found",
        detail=(
            "We could not find an email address. Without one you may be "
            "unreachable even if your application is otherwise successful."
        ),
        fix="Put your email near the top of the page, as plain text.",
    )


@check
def missing_phone(context: AtsContext) -> AtsFinding | None:
    if context.document.contact.phone:
        return None
    return AtsFinding(
        rule_id=AtsRuleId.MISSING_PHONE,
        severity=AtsSeverity.MINOR,
        deduction=10,
        title="No phone number found",
        detail=(
            "We could not find a phone number. Some application forms populate "
            "this field from the resume and reject the submission without it."
        ),
        fix="Add your phone number beside your email, including the country code.",
    )


# -------------------------------------------------------------- formatting ---


@check
def unparseable_dates(context: AtsContext) -> AtsFinding | None:
    entries = [item.dates for item in context.document.experience]
    entries += [project.dates for project in context.document.projects]
    dated = [d for d in entries if d.raw]
    if len(dated) < 2:
        return None

    parsed = sum(1 for d in dated if d.start_year is not None)
    if parsed / len(dated) >= _DATE_PARSE_FLOOR:
        return None

    return AtsFinding(
        rule_id=AtsRuleId.UNPARSEABLE_DATES,
        severity=AtsSeverity.MAJOR,
        deduction=6,
        title="Dates in an unusual format",
        detail=(
            f"We could only read {parsed} of {len(dated)} date ranges. Screening "
            "systems use dates to calculate your years of experience, and one they "
            "cannot read counts as zero."
        ),
        fix='Use a consistent format such as "Jun 2024 – Aug 2025".',
        occurrences=len(dated) - parsed,
    )


@check
def exotic_fonts(context: AtsContext) -> AtsFinding | None:
    unusual = context.signals.unusual_fonts
    if not unusual:
        return None
    return AtsFinding(
        rule_id=AtsRuleId.EXOTIC_FONTS,
        severity=AtsSeverity.MINOR,
        deduction=5,
        title="Uncommon fonts",
        detail=(
            f"This resume uses {', '.join(sorted(unusual)[:3])}. Unusual fonts do "
            "not always embed correctly, and text can be extracted as nonsense "
            "when they do not."
        ),
        fix="Stick to widely available fonts: Arial, Calibri, Garamond or Times.",
    )


@check
def excessive_length(context: AtsContext) -> AtsFinding | None:
    pages = context.extracted.page_count
    months = context.document.total_experience_months()

    # Judged against experience, not a flat rule: a long resume is padding for a
    # student and entirely reasonable for someone with ten years behind them.
    if months >= 60 or pages <= _PAGE_LIMIT_ENTRY_LEVEL:
        return None

    return AtsFinding(
        rule_id=AtsRuleId.EXCESSIVE_LENGTH,
        severity=AtsSeverity.MINOR,
        deduction=8,
        title=f"{pages} pages is long for this much experience",
        detail=(
            f"Your resume runs to {pages} pages with about {months // 12} years of "
            "experience recorded. Early-career resumes are usually stronger at one "
            "or two pages."
        ),
        fix="Cut the weakest items. What you leave out shapes the read as much as what you keep.",
    )


@check
def hidden_text(context: AtsContext) -> AtsFinding | None:
    hidden = context.extracted.hidden_lines
    if not hidden:
        return None

    return AtsFinding(
        rule_id=AtsRuleId.HIDDEN_TEXT,
        severity=AtsSeverity.CRITICAL,
        deduction=20,
        title="Hidden text detected",
        detail=(
            f"This resume contains {len(hidden)} line(s) of text that is invisible "
            "when read — white on white, or set at an unreadably small size. Many "
            "employers treat this as an attempt to game keyword filters and "
            "discard the application outright. We have excluded it from your "
            "analysis."
        ),
        fix="Remove the hidden text. It cannot help you and it can disqualify you.",
        occurrences=len(hidden),
    )


@check
def unprofessional_filename(context: AtsContext) -> AtsFinding | None:
    if filename_is_professional(context.filename):
        return None
    return AtsFinding(
        rule_id=AtsRuleId.UNPROFESSIONAL_FILENAME,
        severity=AtsSeverity.MINOR,
        deduction=2,
        title="Filename could be clearer",
        detail=(
            f'Your file is named "{context.filename}". Recruiters download dozens '
            "of these into one folder, and a name that identifies you is easier to "
            "find again."
        ),
        fix="Rename it to something like Firstname_Lastname_Resume.pdf.",
    )


# ------------------------------------------------------------------ runner ---


def run(context: AtsContext) -> AtsReport:
    """Run every registered check and collect the findings."""
    findings = [finding for finding in (rule(context) for rule in _REGISTRY) if finding]

    return AtsReport(
        findings=findings,
        hidden_text_detected=bool(context.extracted.hidden_lines),
        checks_run=len(_REGISTRY),
    )


def registered_rules() -> tuple[str, ...]:
    return tuple(rule.__name__ for rule in _REGISTRY)
