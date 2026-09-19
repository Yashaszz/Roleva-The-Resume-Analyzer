"""Contact detail extraction.

This runs early and deterministically for one reason beyond filling in the
resume model: **it feeds the PII redactor**. Nothing identifying can be masked
before an LLM call unless it has first been found, so this is the step that
makes the privacy guarantee possible.

Everything here is regex and position, never a model — the values being located
are precisely the ones that must not leave the process.
"""

from __future__ import annotations

import re

from roleva.models.resume import ContactInfo

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

#: Conservative on purpose: requires a separator or a leading +/(, so that
#: metrics ("40000 requests") and year ranges are not read as phone numbers.
_PHONE = re.compile(
    r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?|\d{2,5}[\s.-])\d{2,4}[\s.-]?\d{2,6}(?![\w.])"
)

_URL = re.compile(
    r"\b(?:https?://|www\.)[^\s<>\"')\]]+"
    r"|\b(?:linkedin\.com|github\.com|gitlab\.com|behance\.net|dribbble\.com|medium\.com)"
    r"/[^\s<>\"')\]]+",
    re.IGNORECASE,
)

#: "Pune, Maharashtra" or "Bengaluru, India" — a place, not a job title.
#: Spaces are matched explicitly rather than with \s, which would let a match
#: run across a line break and swallow the name on the line above.
_LOCATION = re.compile(
    r"\b([A-Z][a-z]{2,}(?:[ ][A-Z][a-z]{2,})?),[ ]*([A-Z][a-z]{2,}(?:[ ][A-Z][a-z]{2,})?)\b"
)

#: Words that rule a line out as a person's name.
_NOT_A_NAME = frozenset(
    {
        "resume",
        "curriculum",
        "vitae",
        "cv",
        "profile",
        "summary",
        "contact",
        "engineer",
        "developer",
        "analyst",
        "manager",
        "intern",
        "student",
        "designer",
        "consultant",
        "scientist",
        "experience",
        "education",
        "skills",
        "objective",
        "phone",
        "email",
        "address",
    }
)

#: A name is one to four capitalised words, optionally with initials.
_NAME_SHAPE = re.compile(r"^[A-Z][a-zA-Z.'’-]+(?:\s+[A-Z][a-zA-Z.'’-]+){0,3}$")


def _looks_like_a_name(line: str) -> bool:
    stripped = line.strip()
    if not (3 < len(stripped) <= 50):
        return False
    if any(char.isdigit() for char in stripped):
        return False
    if any(word.lower().strip(".,") in _NOT_A_NAME for word in stripped.split()):
        return False
    if "@" in stripped or "|" in stripped:
        return False
    return bool(_NAME_SHAPE.match(stripped))


def find_name(text: str, *, search_lines: int = 8) -> str | None:
    """The candidate's name, taken from the top of the document.

    Position carries most of the signal: a resume's first non-empty line is
    almost always the name. Searching the whole document would turn every
    capitalised employer into a candidate.
    """
    for line in text.split("\n")[:search_lines]:
        if _looks_like_a_name(line):
            return line.strip()
    return None


def find_email(text: str) -> str | None:
    match = _EMAIL.search(text)
    return match.group() if match else None


def find_phone(text: str) -> str | None:
    """The first plausible phone number.

    Only the top of the document is searched: a number further down is far more
    likely to be a metric in a bullet than a contact detail.
    """
    head = "\n".join(text.split("\n")[:10])
    match = _PHONE.search(head)
    if not match:
        return None
    candidate = match.group().strip()
    digits = sum(char.isdigit() for char in candidate)
    # Ten is the floor for a dialable number anywhere Roleva targets, and it
    # is what separates a phone number from a pair of years.
    return candidate if 10 <= digits <= 15 else None


def find_links(text: str, *, search_lines: int = 10) -> list[str]:
    head = "\n".join(text.split("\n")[:search_lines])
    seen: list[str] = []
    for match in _URL.finditer(head):
        link = match.group().rstrip(".,;)")
        if link not in seen:
            seen.append(link)
    return seen


def find_location(text: str, *, search_lines: int = 8) -> str | None:
    head = "\n".join(text.split("\n")[:search_lines])
    for match in _LOCATION.finditer(head):
        candidate = match.group()
        # Skip matches that are really "Company, Role" pairs.
        if any(word.lower() in _NOT_A_NAME for word in candidate.replace(",", " ").split()):
            continue
        return candidate
    return None


def extract_contact(text: str) -> ContactInfo:
    """Everything identifying that can be found, so it can all be redacted."""
    return ContactInfo(
        name=find_name(text),
        email=find_email(text),
        phone=find_phone(text),
        location=find_location(text),
        links=find_links(text),
    )


def completeness(contact: ContactInfo) -> float:
    """How much of the expected contact block is present, 0.0-1.0.

    Feeds both `parse_confidence` and the ATS checks: a resume with no email is
    not merely incomplete, it is unreachable.
    """
    present = sum(
        [
            bool(contact.name),
            bool(contact.email),
            bool(contact.phone),
            bool(contact.links),
        ]
    )
    return present / 4
