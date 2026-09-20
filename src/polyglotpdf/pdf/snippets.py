"""Vector snippets of inline formulas.

Each inline formula (placeholder) gets its own page in an in-memory document:
a copy of the original page from which every glyph except the formula's glyphs,
and every drawing outside the formula's box, has been removed. The renderer then
places that page, clipped to the formula, next to the translated words with
``show_pdf_page``. The formula keeps its exact vector glyphs (and its text stays
selectable), and neighbouring text can never leak into the clip.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pymupdf

from ..model import BBox
from .content_filter import CullPredicate, ElementKind, PointIndex, filter_page_content


@dataclass(frozen=True, slots=True)
class SnippetRequest:
    points: tuple[tuple[float, float], ...]  # origins of the formula's glyphs
    clip: BBox  # area of the formula on the original page


def _outside(areas: Sequence[BBox]) -> CullPredicate:
    def cull(box: BBox, _kind: ElementKind) -> bool:
        return not any(area.contains(box, 0.3) for area in areas)

    return cull


class SnippetFactory:
    def __init__(self, source: pymupdf.Document) -> None:
        self.source = source
        self.doc = pymupdf.open()

    def create(self, page_index: int, requests: Sequence[SnippetRequest]) -> list[int]:
        """Return, for each request, the page number (in :attr:`doc`) holding only its content."""
        if not requests:
            return []
        # Stage 1: one copy of the page keeping every requested glyph (cheap to copy later).
        self.doc.insert_pdf(self.source, from_page=page_index, to_page=page_index)
        base = self.doc.page_count - 1
        wanted = PointIndex(point for request in requests for point in request.points)
        filter_page_content(
            self.doc[base],
            remove_glyph=wanted.excludes,
            cull=_outside([request.clip for request in requests]),
        )
        # Stage 2: one page per formula.
        pages: list[int] = []
        for request in requests:
            self.doc.fullcopy_page(base)
            number = self.doc.page_count - 1
            filter_page_content(
                self.doc[number],
                remove_glyph=PointIndex(request.points).excludes,
                cull=_outside([request.clip]),
            )
            pages.append(number)
        return pages

    def close(self) -> None:
        self.doc.close()
