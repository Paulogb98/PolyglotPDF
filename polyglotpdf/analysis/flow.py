"""Logical translation units: whole paragraphs, even across columns and pages.

Translating complete paragraphs gives better results than translating sentences
or clauses in isolation: the translator sees whole sentences plus the context
around them (pronouns, terminology, register). Studies of neural and LLM-based
translation consistently report gains from paragraph/document context over
sentence-by-sentence translation.

PDF blocks stop at column and page boundaries, so a paragraph that continues in
the next column or page arrives as fragments. This module links those fragments
back into one unit; the renderer then flows the translation through the
original areas in order, like linked text frames in a layout program.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from ..model import Block, BlockRole, DocumentLayout

#: Blocks that may sit between two parts of a paragraph (page furniture and floats).
_SKIPPABLE = frozenset(
    {
        BlockRole.HEADER_FOOTER,
        BlockRole.NON_TEXT,
        BlockRole.FOOTNOTE,
        BlockRole.FIGURE_TEXT,
        BlockRole.CAPTION,
        BlockRole.TABLE,
        BlockRole.ROTATED,
    }
)
_TERMINAL = frozenset(".!?:…")
_CLOSERS = frozenset("\"'”’»)]")
MAX_BLOCKS = 4
MAX_CHARS = 9000


def translation_units(layout: DocumentLayout, roles: Collection[BlockRole]) -> list[list[Block]]:
    """Group the blocks to translate into units, in reading order.

    A paragraph continues into the next paragraph block when only skippable blocks
    (headers, footnotes, figures, captions, tables...) lie between them and the text
    shows it was interrupted (see :func:`continues`). Headings, list items,
    formulas and other blocks break the flow.
    """
    units: list[list[Block]] = []
    open_unit: list[Block] | None = None
    for page in layout.pages:
        if page.scanned:
            open_unit = None
            continue
        for block in page.blocks:
            if block.role is BlockRole.PARAGRAPH and block.role in roles:
                if open_unit is not None and continues(open_unit, block):
                    open_unit.append(block)
                else:
                    open_unit = [block]
                    units.append(open_unit)
                continue
            if block.role in roles:
                units.append([block])
            if block.role not in _SKIPPABLE:
                open_unit = None
    return units


def continues(unit: Sequence[Block], block: Block) -> bool:
    """Does ``block`` continue the paragraph formed by ``unit``?"""
    last = unit[-1]
    if len(unit) >= MAX_BLOCKS or sum(map(_length, unit)) + _length(block) > MAX_CHARS:
        return False
    if block.page not in (last.page, last.page + 1):
        return False
    style_a, size_a, _ = last.dominant()
    style_b, size_b, _ = block.dominant()
    if abs(size_a - size_b) > 0.6 or style_a.family is not style_b.family:
        return False
    head = _first_char(block)
    if head is not None and head.islower():
        return True  # "… with the" | "results of …"
    tail = _last_char(last)
    return tail is not None and tail not in _TERMINAL and len(last.lines) >= 2


def _length(block: Block) -> int:
    return sum(1 for _ in block.chars)


def _first_char(block: Block) -> str | None:
    return next((ch.c for ch in block.chars if not ch.c.isspace()), None)


def _last_char(block: Block) -> str | None:
    for ch in reversed(list(block.chars)):
        if not ch.c.isspace() and ch.c not in _CLOSERS:
            return ch.c
    return None
