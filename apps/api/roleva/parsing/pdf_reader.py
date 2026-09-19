"""PDF text extraction with layout, typography and character offsets.

A PDF has no reading order. It is a set of positioned glyph runs, and the order
they appear in the file is whatever the producing application happened to emit.
Sorting them top-to-bottom is the single most common parsing failure: on a
two-column resume it interleaves the sidebar with the main column and produces
text that reads like nonsense — and every downstream stage then inherits that.

So extraction here does three things beyond pulling out strings:

  * **Column detection**, by finding a vertical gutter no text crosses.
  * **Character offsets** for every line, so any later claim about the resume can
    be verified against the exact range it came from.
  * **Typography and colour**, which the section detector needs to recognise
    headings, and which is the only way to spot white-on-white hidden text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

#: PyMuPDF span flag bits.
_FLAG_ITALIC = 1 << 1
_FLAG_BOLD = 1 << 4

#: Text at or above this lightness on every channel is invisible on white.
_NEAR_WHITE = 0xF0

#: Font sizes below this cannot be read by a human.
_MIN_VISIBLE_SIZE = 1.5

#: A candidate gutter must be at least this wide, as a share of page width.
#: Narrower gaps are ordinary word spacing rather than a column boundary.
_MIN_GUTTER_RATIO = 0.03

#: Each column must hold at least this share of the page's blocks. Guards
#: against a single stray element being promoted to a "column".
_MIN_COLUMN_SHARE = 0.15


@dataclass(frozen=True)
class Span:
    """One run of text sharing a font, size and colour."""

    text: str
    font: str
    size: float
    color: int
    flags: int
    bbox: tuple[float, float, float, float]

    @property
    def is_bold(self) -> bool:
        return bool(self.flags & _FLAG_BOLD) or "bold" in self.font.lower()

    @property
    def is_italic(self) -> bool:
        return bool(self.flags & _FLAG_ITALIC) or "italic" in self.font.lower()

    @property
    def is_hidden(self) -> bool:
        """Invisible to a reader but present in the text layer.

        Almost always deliberate: keyword stuffing, or instructions aimed at an
        automated reader. Roleva strips this before any LLM call and reports it
        rather than quietly benefiting from it.
        """
        if self.size < _MIN_VISIBLE_SIZE:
            return True
        red, green, blue = (self.color >> 16) & 0xFF, (self.color >> 8) & 0xFF, self.color & 0xFF
        return red >= _NEAR_WHITE and green >= _NEAR_WHITE and blue >= _NEAR_WHITE


@dataclass
class Line:
    """A visual line of text, with its position in the reconstructed document."""

    spans: list[Span]
    bbox: tuple[float, float, float, float]
    page: int
    column: int
    start: int = 0
    end: int = 0

    @property
    def text(self) -> str:
        return "".join(span.text for span in self.spans)

    @property
    def max_size(self) -> float:
        return max((span.size for span in self.spans), default=0.0)

    @property
    def is_bold(self) -> bool:
        """True when the whole line is bold, not merely part of it."""
        visible = [span for span in self.spans if span.text.strip()]
        return bool(visible) and all(span.is_bold for span in visible)

    @property
    def is_hidden(self) -> bool:
        visible = [span for span in self.spans if span.text.strip()]
        return bool(visible) and all(span.is_hidden for span in visible)


@dataclass
class ExtractedDocument:
    """The output of extraction: reading-order text, plus everything needed to
    locate and characterise any part of it."""

    text: str
    lines: list[Line]
    page_count: int
    #: Lines that were dropped for being invisible. Reported to the user as an
    #: ATS finding, and never sent to a model.
    hidden_lines: list[Line] = field(default_factory=list)
    #: Pages found to have more than one column, for ATS reporting.
    multi_column_pages: list[int] = field(default_factory=list)
    #: Lines removed as repeated page headers or footers.
    repeated_lines: list[str] = field(default_factory=list)

    @property
    def body_size(self) -> float:
        """Median font size, treated as the body text size.

        Headings are recognised partly by being larger than this, so it has to
        be measured per document — a resume set in 9pt and one set in 12pt
        should behave identically.
        """
        sizes = sorted(line.max_size for line in self.lines if line.text.strip())
        return sizes[len(sizes) // 2] if sizes else 0.0

    def line_at(self, offset: int) -> Line | None:
        for line in self.lines:
            if line.start <= offset < line.end:
                return line
        return None


def _raw_lines(page: pymupdf.Page, page_number: int) -> list[Line]:
    lines: list[Line] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:  # skip images
            continue
        for raw in block.get("lines", []):
            spans = [
                Span(
                    text=span["text"],
                    font=span.get("font", ""),
                    size=round(float(span.get("size", 0.0)), 2),
                    color=int(span.get("color", 0)),
                    flags=int(span.get("flags", 0)),
                    bbox=tuple(span["bbox"]),
                )
                for span in raw.get("spans", [])
            ]
            if not any(span.text.strip() for span in spans):
                continue
            lines.append(Line(spans=spans, bbox=tuple(raw["bbox"]), page=page_number, column=0))
    return lines


def detect_columns(lines: list[Line], page_width: float) -> list[float]:
    """Find vertical gutters that no line crosses.

    Rather than clustering x-positions — which confuses indented text with a
    second column — this looks for a vertical band containing no text at all.
    A real column boundary is a gap that runs the height of the page; an indent
    is not.

    Returns the x-positions of any gutters found, left to right.
    """
    if len(lines) < 6 or page_width <= 0:
        return []

    # Sweep across the page in 1% steps, keeping positions no line spans.
    step = page_width / 100
    free: list[float] = []
    for index in range(20, 81):  # ignore the outer 20%, where margins live
        x = index * step
        if not any(line.bbox[0] < x < line.bbox[2] for line in lines):
            free.append(x)

    if not free:
        return []

    # Group adjacent free positions into bands, and keep bands wide enough to be
    # a deliberate gutter.
    bands: list[list[float]] = [[free[0]]]
    for x in free[1:]:
        if x - bands[-1][-1] <= step * 1.5:
            bands[-1].append(x)
        else:
            bands.append([x])

    gutters = []
    for band in bands:
        width = band[-1] - band[0]
        if width < page_width * _MIN_GUTTER_RATIO:
            continue
        centre = (band[0] + band[-1]) / 2
        left = sum(1 for line in lines if line.bbox[2] <= centre)
        right = len(lines) - left
        minimum = len(lines) * _MIN_COLUMN_SHARE
        if left >= minimum and right >= minimum:
            gutters.append(centre)

    return gutters


def _assign_columns(lines: list[Line], gutters: list[float]) -> None:
    for line in lines:
        centre = (line.bbox[0] + line.bbox[2]) / 2
        line.column = sum(1 for gutter in gutters if centre > gutter)


def _reading_order(lines: list[Line]) -> list[Line]:
    """Column first, then top to bottom, then left to right.

    Sorting by vertical position alone is what scrambles two-column resumes.
    """
    return sorted(lines, key=lambda line: (line.column, round(line.bbox[1], 1), line.bbox[0]))


def _strip_repeated(pages: dict[int, list[Line]]) -> tuple[dict[int, list[Line]], list[str]]:
    """Remove page headers and footers that repeat across pages.

    Otherwise a two-page resume yields two contact blocks, and the second is
    parsed as though the candidate listed their details twice.
    """
    if len(pages) < 2:
        return pages, []

    def edge_text(lines: list[Line], top: bool) -> str:
        candidates = sorted(lines, key=lambda line: line.bbox[1], reverse=not top)
        return candidates[0].text.strip() if candidates else ""

    removed: list[str] = []
    for at_top in (True, False):
        texts = [edge_text(lines, at_top) for lines in pages.values() if lines]
        # Page numbers differ per page, so compare with digits removed.
        normalised = [
            "".join(char for char in text if not char.isdigit()).strip() for text in texts
        ]
        if len(normalised) >= 2 and len(set(normalised)) == 1 and normalised[0]:
            removed.append(texts[0])
            for lines in pages.values():
                if not lines:
                    continue
                target = max(lines, key=lambda line: line.bbox[1] * (-1 if at_top else 1))
                lines.remove(target)

    return pages, removed


def extract(doc: pymupdf.Document) -> ExtractedDocument:
    """Extract reading-order text with offsets, typography and layout findings."""
    per_page: dict[int, list[Line]] = {}
    multi_column: list[int] = []

    for index, page in enumerate(doc, start=1):
        lines = _raw_lines(page, index)
        gutters = detect_columns(lines, page.rect.width)
        if gutters:
            multi_column.append(index)
        _assign_columns(lines, gutters)
        per_page[index] = _reading_order(lines)

    per_page, repeated = _strip_repeated(per_page)

    ordered: list[Line] = []
    for index in sorted(per_page):
        ordered.extend(per_page[index])

    # Hidden text is separated out before the document text is built, so it can
    # never reach a model or count as evidence — but it is kept for reporting.
    hidden = [line for line in ordered if line.is_hidden]
    visible = [line for line in ordered if not line.is_hidden]

    pieces: list[str] = []
    cursor = 0
    for line in visible:
        text = line.text
        line.start = cursor
        line.end = cursor + len(text)
        pieces.append(text)
        cursor = line.end + 1  # for the newline joiner
    body = "\n".join(pieces)

    return ExtractedDocument(
        text=body,
        lines=visible,
        page_count=doc.page_count,
        hidden_lines=hidden,
        multi_column_pages=multi_column,
        repeated_lines=repeated,
    )
