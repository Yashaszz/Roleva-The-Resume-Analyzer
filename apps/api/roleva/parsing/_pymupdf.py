"""Typed helpers over PyMuPDF.

PyMuPDF ships incomplete type information: `Document` is iterable at runtime but
not described as such, and several methods are untyped. Rather than scattering
ignores through the parsing code, the awkwardness is contained here.
"""

from __future__ import annotations

from typing import Any

import pymupdf

#: Re-exported so parsing modules never import pymupdf directly.
Document = pymupdf.Document
Page = pymupdf.Page


def pages(doc: pymupdf.Document) -> list[pymupdf.Page]:
    """Every page, as a list.

    `for page in doc` works at runtime but is not in the stubs, and a resume is
    at most ten pages, so materialising the list costs nothing.
    """
    return [doc.load_page(index) for index in range(doc.page_count)]


def text_dict(page: pymupdf.Page) -> dict[str, Any]:
    """The page's structured content: blocks, lines, spans, fonts and colours."""
    result: dict[str, Any] = page.get_text("dict")
    return result


def plain_text(page: pymupdf.Page) -> str:
    result: str = page.get_text()
    return result


def image_count(page: pymupdf.Page) -> int:
    images: list[Any] = page.get_images()
    return len(images)


def open_stream(data: bytes) -> pymupdf.Document:
    doc: pymupdf.Document = pymupdf.open(stream=data, filetype="pdf")
    return doc


def close(doc: pymupdf.Document) -> None:
    doc.close()


def table_row_counts(page: pymupdf.Page) -> list[int]:
    """Row counts of any tables on the page, empty when there are none.

    Table detection varies by document and can raise on unusual ones, so a
    failure here means 'no tables found' rather than a failed analysis.
    """
    try:
        finder = page.find_tables()
    except Exception:  # pragma: no cover - depends on document internals
        return []
    return [int(table.row_count) for table in finder.tables]


def rect(bbox: Any) -> pymupdf.Rect:
    box: pymupdf.Rect = pymupdf.Rect(bbox)
    return box


def area(box: Any) -> float:
    return abs(float(box.get_area()))
