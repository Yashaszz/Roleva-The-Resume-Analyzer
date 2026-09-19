"""Job description cleaning.

Roughly half a corporate job posting is not about the job: company history,
benefits, the EEO statement, application instructions. Left in, it poisons
everything downstream — "401(k)" and "dental" become requirements, the
company's founding year becomes a date, and keyword matching scores a candidate
against the perks.

Cleaning happens before extraction so the model sees only the parts that
describe the role, which also keeps the request smaller on a request-limited
tier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from roleva.api.errors import ErrorCode, RolevaError
from roleva.config import Settings

#: Section headings whose content is never a requirement.
_BOILERPLATE_HEADINGS = (
    "about us",
    "about the company",
    "about our company",
    "who we are",
    "our mission",
    "our values",
    "our culture",
    "company overview",
    "benefits",
    "perks",
    "what we offer",
    "compensation",
    "salary",
    "pay range",
    "total rewards",
    "why join",
    "why work",
    "equal opportunity",
    "equal employment",
    "eeo",
    "diversity",
    "diversity and inclusion",
    "accommodations",
    "accessibility statement",
    "how to apply",
    "application process",
    "to apply",
    "next steps",
    "legal",
    "privacy",
    "disclaimer",
    "note to recruiters",
    "agency notice",
    "recruitment agencies",
)

#: Phrases that mark a paragraph as boilerplate even without a heading.
_BOILERPLATE_PHRASES = (
    "equal opportunity employer",
    "without regard to race",
    "reasonable accommodation",
    "protected veteran",
    "applicants will receive consideration",
    "e-verify",
    "background check",
    "drug screening",
    "unsolicited resumes",
    "staffing agencies",
    "we are unable to respond",
    "due to the volume of applications",
    "no visa sponsorship",
    "click apply",
    "apply now",
    "submit your resume",
    "applications sent by email",
)

#: Benefit words. A line thick with these is a perks list.
_BENEFIT_WORDS = (
    "401(k)",
    "401k",
    "dental",
    "vision",
    "medical insurance",
    "health insurance",
    "paid time off",
    "pto",
    "parental leave",
    "maternity",
    "paternity",
    "free lunch",
    "snacks",
    "gym",
    "wellness",
    "stipend",
    "equity",
    "stock options",
    "pension",
    "life insurance",
    "sick leave",
    "holidays",
)

_HEADING = re.compile(r"^[^a-z]{0,4}([A-Za-z][A-Za-z\s/&'-]{2,45})[:\s]*$")


@dataclass
class CleanedJd:
    text: str
    removed_blocks: list[str] = field(default_factory=list)
    #: True when the posting is short enough that the analysis will be thin.
    is_thin: bool = False

    @property
    def removed_chars(self) -> int:
        return sum(len(block) for block in self.removed_blocks)


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not (2 < len(stripped) <= 50):
        return False
    if stripped.endswith((".", "!", "?")):
        return False
    return bool(_HEADING.match(stripped)) or stripped.isupper()


def _is_boilerplate_heading(line: str) -> bool:
    cleaned = re.sub(r"[^a-z\s]", " ", line.lower()).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return any(cleaned == phrase or cleaned.startswith(phrase) for phrase in _BOILERPLATE_HEADINGS)


def _is_boilerplate_block(block: str) -> bool:
    lowered = block.lower()

    if any(phrase in lowered for phrase in _BOILERPLATE_PHRASES):
        return True

    # A block dense with benefit words is a perks list whatever it is titled.
    hits = sum(1 for word in _BENEFIT_WORDS if word in lowered)
    if hits >= 3:
        return True

    return False


def _split_blocks(text: str) -> list[str]:
    """Split on blank lines, then further on heading lines.

    Postings are inconsistently formatted, so a block boundary is either a gap
    or a line that looks like a heading.
    """
    rough = re.split(r"\n\s*\n", text)

    blocks: list[str] = []
    for chunk in rough:
        current: list[str] = []
        for line in chunk.split("\n"):
            if _looks_like_heading(line) and current:
                blocks.append("\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            blocks.append("\n".join(current))

    return [block for block in blocks if block.strip()]


def clean(text: str, settings: Settings | None = None) -> CleanedJd:
    """Strip everything that is not about the job.

    Raises when the posting is too short to analyse: a forty-word description
    cannot produce a meaningful requirement list, and pretending otherwise
    would give the user a confident, empty answer.
    """
    config = settings or Settings()
    raw = text.strip()

    if len(raw) < config.min_jd_chars:
        raise RolevaError(ErrorCode.JD_TOO_SHORT)

    kept: list[str] = []
    removed: list[str] = []
    skipping = False

    for block in _split_blocks(raw):
        first_line = block.strip().split("\n")[0]

        if _looks_like_heading(first_line):
            # A boilerplate heading turns off capture until the next heading.
            skipping = _is_boilerplate_heading(first_line)

        if skipping or _is_boilerplate_block(block):
            removed.append(block)
            continue

        kept.append(block)

    cleaned = "\n\n".join(kept).strip()

    # Never strip so much that nothing is left. If the heuristics ate the whole
    # posting, the original is a safer input than an empty string.
    if len(cleaned) < config.min_jd_chars // 2:
        return CleanedJd(text=raw, removed_blocks=[], is_thin=len(raw) < config.warn_jd_chars)

    return CleanedJd(
        text=cleaned,
        removed_blocks=removed,
        is_thin=len(raw) < config.warn_jd_chars,
    )
