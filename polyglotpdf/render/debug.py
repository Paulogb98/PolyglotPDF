"""Annotated copy of a document showing how it was analysed (``polyglotpdf inspect``).

Solid boxes are translated, dashed boxes are kept in the original language; thin
red boxes mark inline formulas/scripts and dotted grey boxes are figure regions.
"""

from __future__ import annotations

import pymupdf

from ..model import BlockRole, DocumentLayout, union_all

_COLORS: dict[BlockRole, tuple[float, float, float]] = {
    BlockRole.PARAGRAPH: (0.13, 0.40, 0.85),
    BlockRole.HEADING: (0.05, 0.55, 0.20),
    BlockRole.TITLE: (0.00, 0.45, 0.10),
    BlockRole.CAPTION: (0.55, 0.25, 0.75),
    BlockRole.LIST_ITEM: (0.10, 0.60, 0.80),
    BlockRole.FOOTNOTE: (0.35, 0.35, 0.70),
    BlockRole.HEADER_FOOTER: (0.50, 0.50, 0.50),
    BlockRole.REFERENCE: (0.90, 0.55, 0.05),
    BlockRole.AUTHOR: (0.80, 0.40, 0.15),
    BlockRole.DISPLAY_MATH: (0.85, 0.10, 0.10),
    BlockRole.FIGURE_TEXT: (0.60, 0.55, 0.10),
    BlockRole.TABLE: (0.15, 0.60, 0.60),
    BlockRole.CODE: (0.40, 0.20, 0.20),
}
_MUTED = (0.65, 0.65, 0.65)
_FORMULA = (0.90, 0.00, 0.00)


def annotate_layout(
    document: pymupdf.Document, layout: DocumentLayout, translatable: set[BlockRole]
) -> None:
    for page_layout in layout.pages:
        page = document[page_layout.index]
        shape = page.new_shape()
        for region in page_layout.graphics:
            shape.draw_rect(pymupdf.Rect(region.as_tuple()))
            shape.finish(color=_MUTED, width=0.4, dashes="[1 2] 0")
        for block in page_layout.blocks:
            color = _COLORS.get(block.role, _MUTED)
            shape.draw_rect(pymupdf.Rect(block.bbox.as_tuple()))
            if block.role in translatable:
                shape.finish(color=color, width=0.9)
            else:
                shape.finish(color=color, width=0.5, dashes="[3 2] 0")
            for run in block.runs.values():
                box = union_all(ch.bbox for ch in run if ch.bbox.area > 0)
                if box is not None:
                    shape.draw_rect(pymupdf.Rect(box.as_tuple()))
                    shape.finish(color=_FORMULA, width=0.35)
        shape.commit()
        for block in page_layout.blocks:
            label = block.role.value + ("" if block.role in translatable else " · kept")
            page.insert_text(
                (block.bbox.x0, max(5.0, block.bbox.y0 - 1.0)),
                label,
                fontsize=4.5,
                fontname="helv",
                color=_COLORS.get(block.role, _MUTED),
            )
