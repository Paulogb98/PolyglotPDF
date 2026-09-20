"""Glyph-precise removal of page content through MuPDF's sanitize filter.

Redaction annotations decide which glyphs to delete from their *font* bounding
boxes, which are much larger than the ink for math fonts (Computer Modern
symbol fonts have a descender close to one em). Redacting a paragraph therefore
also deletes symbols of neighbouring formulas.

This module rewrites the page content stream with MuPDF's sanitize filter and
decides glyph by glyph, using the exact glyph *origin*, so only the glyphs that
were extracted as part of a translated block disappear. The same mechanism
removes vector elements (fraction bars of inline formulas) by bounding box.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

import pymupdf

from ..model import BBox

log = logging.getLogger(__name__)
mupdf: Any = pymupdf.mupdf


class ElementKind(Enum):
    PATH = "path"
    CLIP = "clip"
    GLYPH = "glyph"
    IMAGE = "image"
    SHADING = "shading"
    OTHER = "other"


_KIND_BY_CODE = {
    mupdf.FZ_CULL_PATH_FILL: ElementKind.PATH,
    mupdf.FZ_CULL_PATH_STROKE: ElementKind.PATH,
    mupdf.FZ_CULL_PATH_FILL_STROKE: ElementKind.PATH,
    mupdf.FZ_CULL_PATH_DROP: ElementKind.OTHER,
    mupdf.FZ_CULL_CLIP_PATH_DROP: ElementKind.CLIP,
    mupdf.FZ_CULL_CLIP_PATH_FILL: ElementKind.CLIP,
    mupdf.FZ_CULL_CLIP_PATH_STROKE: ElementKind.CLIP,
    mupdf.FZ_CULL_CLIP_PATH_FILL_STROKE: ElementKind.CLIP,
    mupdf.FZ_CULL_GLYPH: ElementKind.GLYPH,
    mupdf.FZ_CULL_IMAGE: ElementKind.IMAGE,
    mupdf.FZ_CULL_SHADING: ElementKind.SHADING,
}
#: Only drawn elements may be culled; clipping paths and glyphs are left alone
#: (glyphs are handled by the text filter).
_CULLABLE = frozenset({ElementKind.PATH, ElementKind.IMAGE, ElementKind.SHADING})

GlyphPredicate = Callable[[float, float], bool]
CullPredicate = Callable[[BBox, ElementKind], bool]


class PointIndex:
    """Spatial hash answering "is a registered point within ``tolerance`` of (x, y)?"."""

    def __init__(self, points: Iterable[tuple[float, float]], tolerance: float = 0.25) -> None:
        self.tolerance = tolerance
        self._cells: dict[tuple[int, int], list[tuple[float, float]]] = {}
        self._count = 0
        for x, y in points:
            self._cells.setdefault((math.floor(x), math.floor(y)), []).append((x, y))
            self._count += 1

    def contains(self, x: float, y: float) -> bool:
        cx, cy, tol = math.floor(x), math.floor(y), self.tolerance
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for px, py in self._cells.get((cx + dx, cy + dy), ()):
                    if abs(px - x) <= tol and abs(py - y) <= tol:
                        return True
        return False

    def excludes(self, x: float, y: float) -> bool:
        return not self.contains(x, y)

    def __len__(self) -> int:
        return self._count


@dataclass(slots=True)
class FilterStats:
    removed: int = 0
    kept: int = 0
    culled: int = 0
    errors: int = 0


_SanitizeBase: Any = mupdf.PdfSanitizeFilterOptions2
_FactoryBase: Any = mupdf.PdfFilterFactory2


class _SanitizeOptions(_SanitizeBase):
    """SWIG director: MuPDF calls these methods for every glyph and drawn element."""

    def __init__(
        self, matrix: pymupdf.Matrix, remove: GlyphPredicate, cull: CullPredicate | None
    ) -> None:
        super().__init__()
        self.use_virtual_text_filter()
        if cull is not None:
            self.use_virtual_culler()
        self._m = matrix  # PDF user space -> PyMuPDF page coordinates
        self._remove = remove
        self._cull = cull
        self.stats = FilterStats()

    def text_filter(
        self, ctx: Any, ucsbuf: Any, ucslen: Any, trm: Any, ctm: Any, *rest: Any
    ) -> int:
        try:
            # Glyph origin in user space: text rendering matrix translated by the CTM.
            x = trm.e * ctm.a + trm.f * ctm.c + ctm.e
            y = trm.e * ctm.b + trm.f * ctm.d + ctm.f
            m = self._m
            if self._remove(x * m.a + y * m.c + m.e, x * m.b + y * m.d + m.f):
                self.stats.removed += 1
                return 1
            self.stats.kept += 1
            return 0
        except Exception:  # never let an exception cross the C boundary
            self.stats.errors += 1
            return 0

    def culler(self, ctx: Any, bbox: Any, kind_code: Any) -> int:
        try:
            kind = _KIND_BY_CODE.get(int(kind_code), ElementKind.OTHER)
            if kind not in _CULLABLE or self._cull is None:
                return 0
            rect = pymupdf.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1) * self._m
            if self._cull(BBox(rect.x0, rect.y0, rect.x1, rect.y1), kind):
                self.stats.culled += 1
                return 1
            return 0
        except Exception:
            self.stats.errors += 1
            return 0


class _SanitizeFactory(_FactoryBase):
    def __init__(self, options: _SanitizeOptions) -> None:
        super().__init__()
        self.use_virtual_filter()
        self._options = options

    def filter(
        self, ctx: Any, doc: Any, chain: Any, struct_parents: Any, transform: Any, options: Any
    ) -> Any:
        return mupdf.ll_pdf_new_sanitize_filter(
            doc, chain, struct_parents, transform, options, self._options.internal()
        )


def filter_page_content(
    page: pymupdf.Page, *, remove_glyph: GlyphPredicate, cull: CullPredicate | None = None
) -> FilterStats:
    """Rewrite the page contents, dropping glyphs whose origin satisfies ``remove_glyph``.

    ``cull`` (optional) receives the bounding box of every path, image and shading in
    page coordinates and returns True to drop it. Form XObjects are processed too;
    shared forms are instanced so other pages are unaffected.
    """
    sanitize = _SanitizeOptions(page.transformation_matrix, remove_glyph, cull)
    factory = _SanitizeFactory(sanitize)
    options = mupdf.PdfFilterOptions()
    options.recurse = 1
    options.instance_forms = 1
    options.no_update = 0
    options.add_factory(factory.internal())
    pdf_page = _as_pdf_page(page)
    mupdf.pdf_filter_page_contents(pdf_page.doc(), pdf_page, options)
    if sanitize.stats.errors:
        log.warning("%d content element(s) could not be filtered", sanitize.stats.errors)
    return sanitize.stats


def _as_pdf_page(page: pymupdf.Page) -> Any:
    this = page.this
    if isinstance(this, mupdf.PdfPage):
        return this
    return mupdf.pdf_page_from_fz_page(this)
