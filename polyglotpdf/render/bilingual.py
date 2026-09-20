"""Side-by-side bilingual output: original page on the left, translation on the right."""

from __future__ import annotations

from collections.abc import Sequence

import pymupdf


def side_by_side(
    original: pymupdf.Document, translated: pymupdf.Document, pages: Sequence[int]
) -> pymupdf.Document:
    output = pymupdf.open()
    for index in pages:
        rect = original[index].rect
        page = output.new_page(width=rect.width * 2, height=rect.height)
        page.show_pdf_page(pymupdf.Rect(0, 0, rect.width, rect.height), original, index)
        page.show_pdf_page(
            pymupdf.Rect(rect.width, 0, rect.width * 2, rect.height), translated, index
        )
    return output
