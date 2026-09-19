"""Layout facts an ATS would trip over.

These are gathered while the PDF is still open, because they are properties of
the document rather than of its text — a table is invisible once the words have
been extracted, which is precisely why table layouts break automated parsers
without the candidate ever noticing.

Everything here is measured. No judgement, no model: an ATS check should be
able to say "this is in a table, on page two" and be right.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from roleva.parsing import _pymupdf as mu

#: Share of page height at the top and bottom treated as margin. Content placed
#: there is often skipped by parsers that read only the main text frame.
_MARGIN_BAND = 0.08

#: An image covering more than this share of a page is a design element rather
#: than a logo, and any text it carries is unreadable to a parser.
_LARGE_IMAGE_RATIO = 0.25

#: Fonts every PDF reader has. Anything else may not embed cleanly.
_SAFE_FONTS = (
    "arial",
    "helvetica",
    "times",
    "calibri",
    "cambria",
    "garamond",
    "georgia",
    "verdana",
    "tahoma",
    "trebuchet",
    "courier",
    "roboto",
    "opensans",
    "lato",
    "liberation",
    "dejavu",
    "nimbus",
    "freesans",
    "freeserif",
    "sans-serif",
    "serif",
)


@dataclass
class AtsSignals:
    """Measured layout facts, one entry per thing an ATS check needs."""

    #: Pages where text sits inside a table structure.
    table_pages: list[int] = field(default_factory=list)
    #: Text found in the top or bottom margin band, by page.
    margin_texts: list[tuple[int, str]] = field(default_factory=list)
    #: Pages carrying an image large enough to be conveying information.
    large_image_pages: list[int] = field(default_factory=list)
    #: Every font family used, lowercased.
    fonts: set[str] = field(default_factory=set)
    #: Fonts outside the set every reader is guaranteed to have.
    unusual_fonts: set[str] = field(default_factory=set)

    @property
    def has_tables(self) -> bool:
        return bool(self.table_pages)

    @property
    def has_margin_content(self) -> bool:
        return bool(self.margin_texts)


def _normalise_font(name: str) -> str:
    """Strip the subset prefix and style suffix PDFs attach to font names.

    "ABCDEF+Arial-BoldMT" and "Arial" are the same typeface, and treating them
    as different would flag every bold word as an unusual font.
    """
    cleaned = name.split("+")[-1]
    cleaned = cleaned.split("-")[0].split(",")[0]
    return cleaned.lower().replace(" ", "")


def _is_safe_font(name: str) -> bool:
    normalised = _normalise_font(name)
    return any(safe in normalised for safe in _SAFE_FONTS)


def _table_pages(doc: mu.Document) -> list[int]:
    """Pages where PyMuPDF finds a table containing text.

    Tables are a genuine ATS hazard: many parsers read cells in storage order
    rather than visual order, which scrambles a résumé laid out as a grid.
    """
    found: list[int] = []
    for index, page in enumerate(mu.pages(doc), start=1):
        if any(rows > 1 for rows in mu.table_row_counts(page)):
            found.append(index)
    return found


def collect(doc: mu.Document) -> AtsSignals:
    """Gather every layout signal in one pass over the document."""
    signals = AtsSignals(table_pages=_table_pages(doc))

    for index, page in enumerate(mu.pages(doc), start=1):
        height = page.rect.height

        page_area = mu.area(page.rect)
        top_band = height * _MARGIN_BAND
        bottom_band = height * (1 - _MARGIN_BAND)

        for block in mu.text_dict(page)["blocks"]:
            if block.get("type") == 1:
                bbox = mu.rect(block["bbox"])
                if page_area and mu.area(bbox) / page_area >= _LARGE_IMAGE_RATIO:
                    signals.large_image_pages.append(index)
                continue

            for line in block.get("lines", []):
                y_top = line["bbox"][1]
                y_bottom = line["bbox"][3]
                text = "".join(span["text"] for span in line.get("spans", [])).strip()

                for span in line.get("spans", []):
                    font = span.get("font", "")
                    if not font:
                        continue
                    signals.fonts.add(_normalise_font(font))
                    if not _is_safe_font(font):
                        signals.unusual_fonts.add(_normalise_font(font))

                # Narrow decorative marks are not content; require real text.
                if text and len(text) > 3 and (y_bottom < top_band or y_top > bottom_band):
                    signals.margin_texts.append((index, text))

        # A page can hold several large images; count it once.
        signals.large_image_pages = sorted(set(signals.large_image_pages))

    return signals
