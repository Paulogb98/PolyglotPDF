"""Frame computation: where and how the text of a block is typeset.

The frame reproduces the original block: position, first baseline, line pitch,
indentation and alignment (justified, centred...). When allowed, it also grows
into the free space around the block, so longer translations need less shrinking.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterator
from itertools import pairwise

from ..config import LayoutSettings
from ..model import BBox, Block, BlockRole, PageLayout, TextStyle
from .typesetter import Align, Frame

_TOL = 1.6


def frame_for(
    block: Block, style: TextStyle, size: float, page: PageLayout, settings: LayoutSettings
) -> Frame:
    box = block.bbox
    column = column_bounds(block, page)
    align = detect_alignment(block, column)
    first_indent, rest_indent = _indents(block, align)

    x0, width = box.x0, box.width
    bottom = box.y1
    if settings.expand_into_free_space:
        if len(block.lines) == 1:
            left, right = _horizontal_room(block, page, column)
            if align is Align.CENTER:
                half = min(box.center_x - left, right - box.center_x)
                x0, width = box.center_x - half, 2 * half
            elif align is Align.RIGHT:
                x0, width = left, box.x1 - left
            else:
                width = right - box.x0
            if width < box.width:
                x0, width = box.x0, box.width
        bottom = _free_bottom(block, page, size)

    return Frame(
        x0=x0,
        top=box.y0,
        width=width,
        # Glyph ink rarely reaches the font's full descender: allow a little slack.
        height=(bottom - box.y0) + 0.15 * size,
        base_size=size,
        first_baseline=block.lines[0].baseline - box.y0,
        line_pitch=_line_pitch(block, size),
        align=align,
        first_indent=first_indent,
        rest_indent=rest_indent,
        style=style,
    )


def column_bounds(block: Block, page: PageLayout) -> tuple[float, float]:
    """Horizontal extent of the text column the block belongs to."""
    center = block.bbox.center_x
    votes: Counter[tuple[float, float]] = Counter()
    for other in page.blocks:
        if (
            other.role is BlockRole.PARAGRAPH
            and len(other.lines) >= 2
            and other.bbox.x0 - 1 <= center <= other.bbox.x1 + 1
        ):
            votes[(round(other.bbox.x0, 1), round(other.bbox.x1, 1))] += len(other.lines)
    if votes:
        (x0, x1), _ = votes.most_common(1)[0]
        return min(x0, block.bbox.x0), max(x1, block.bbox.x1)
    paragraphs = [b.bbox for b in page.blocks if b.role is BlockRole.PARAGRAPH]
    if paragraphs:
        return (
            min(min(b.x0 for b in paragraphs), block.bbox.x0),
            max(max(b.x1 for b in paragraphs), block.bbox.x1),
        )
    return block.bbox.x0, block.bbox.x1


def detect_alignment(block: Block, column: tuple[float, float]) -> Align:
    col_x0, col_x1 = column
    lines = block.lines
    box = block.bbox
    if len(lines) == 1:
        indented = box.x0 - col_x0 > 6
        if indented and abs(box.center_x - (col_x0 + col_x1) / 2) < 3.0:
            return Align.CENTER
        if indented and abs(box.x1 - col_x1) < _TOL:
            return Align.RIGHT
        return Align.LEFT
    rights = [line.bbox.x1 for line in lines[:-1]]
    lefts = [line.bbox.x0 for line in lines[1:]]
    flush_right = all(abs(r - col_x1) < _TOL for r in rights) or (
        len(rights) >= 2 and max(rights) - min(rights) < _TOL
    )
    flush_left = max(lefts) - min(lefts) < _TOL
    centers = [line.bbox.center_x for line in lines]
    if flush_right and flush_left:
        return Align.JUSTIFY
    if max(centers) - min(centers) < 2 * _TOL and not flush_left:
        return Align.CENTER
    if flush_right:
        return Align.RIGHT
    return Align.LEFT


def _indents(block: Block, align: Align) -> tuple[float, float]:
    lines = block.lines
    if align in (Align.CENTER, Align.RIGHT) or len(lines) < 2:
        return 0.0, 0.0
    x0 = block.bbox.x0
    first = max(0.0, lines[0].bbox.x0 - x0)
    rest = max(0.0, min(line.bbox.x0 for line in lines[1:]) - x0)
    if first > 0.4 * block.bbox.width:
        first = 0.0
    return first, rest


def _line_pitch(block: Block, size: float) -> float:
    baselines = [line.baseline for line in block.lines]
    diffs = [b - a for a, b in pairwise(baselines) if b - a > 0.5]
    pitch = statistics.median(diffs) if diffs else 1.2 * size
    return min(max(pitch, 0.95 * size), 2.2 * size)


def _neighbours(block: Block, page: PageLayout) -> Iterator[BBox]:
    for other in page.blocks:
        if other is not block:
            yield other.bbox
    yield from page.obstacles


def _horizontal_room(
    block: Block, page: PageLayout, column: tuple[float, float]
) -> tuple[float, float]:
    box = block.bbox
    left, right = column
    for other in _neighbours(block, page):
        if other.overlap_y(box) <= 0.5:
            continue
        if other.x0 >= box.x1 - 0.5:
            right = min(right, other.x0 - 2.0)
        elif other.x1 <= box.x0 + 0.5:
            left = max(left, other.x1 + 2.0)
    return left, right


def _free_bottom(block: Block, page: PageLayout, size: float) -> float:
    """Lowest y the block may reach: the next element below it, within its column's extent."""
    box = block.bbox
    column_bottom = box.y1
    limit = float("inf")
    for other in _neighbours(block, page):
        if other.overlap_x(box) <= 1.0:
            continue
        column_bottom = max(column_bottom, other.y1)
        if other.y0 >= box.y1 - 0.5:
            limit = min(limit, other.y0 - 0.3 * size)
    return max(box.y1, min(limit, column_bottom))
