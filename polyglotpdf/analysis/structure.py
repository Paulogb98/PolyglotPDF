"""Block refinement.

PDF text extraction groups lines into blocks; that grouping is usually right but
sometimes merges a heading with the following paragraph, or several list items,
into one block. Tables come out as blocks whose lines sit side by side: they are
split into individual cells, each translated and re-typeset in its own box.
"""

from __future__ import annotations

import re
from itertools import pairwise

from ..model import Block, BlockRole, Char, Line, PageLayout, Span, union_all

LIST_MARKER = re.compile(
    r"^\s*(?:[•◦▪▫‣∙●○■□–—*]|\(?\d{1,3}[.)]|\(?[a-z][.)]|\([ivxlc]+\))\s+\S", re.IGNORECASE
)
_CELL_GAP = 1.2  # horizontal gap (in font sizes) that separates two table cells


def refine_page(page: PageLayout) -> None:
    refined: list[Block] = []
    for block in page.blocks:
        refined.extend(split_block(block))
    page.blocks = refined


def split_block(block: Block) -> list[Block]:
    lines = [line for line in block.lines if line.spans]
    if len(lines) < 2:
        return [block]
    if is_tabular(lines):
        return table_cells(block, lines)
    list_mode = sum(1 for line in lines if LIST_MARKER.match(line.text)) >= 2
    groups: list[list[Line]] = [[lines[0]]]
    for previous, line in pairwise(lines):
        if _breaks(previous, line, list_mode):
            groups.append([line])
        else:
            groups[-1].append(line)
    if len(groups) == 1:
        return [block]
    return [
        Block(
            uid=f"{block.uid}.{number}",
            page=block.page,
            bbox=union_all(line.bbox for line in group) or block.bbox,
            lines=group,
        )
        for number, group in enumerate(groups, 1)
    ]


def is_tabular(lines: list[Line]) -> bool:
    """Two or more pairs of lines sharing a vertical band side by side: a table, not prose."""
    side_by_side = 0
    for i, a in enumerate(lines):
        for b in lines[i + 1 :]:
            shared = a.bbox.overlap_y(b.bbox)
            if shared > 0.5 * min(a.bbox.height, b.bbox.height) and a.bbox.overlap_x(b.bbox) < 0:
                side_by_side += 1
                if side_by_side >= 2:
                    return True
    return False


def table_cells(block: Block, lines: list[Line]) -> list[Block]:
    """One block per cell; the classifier later decides which cells hold text."""
    cells: list[Block] = []
    for line in lines:
        for part in split_line(line):
            cells.append(
                Block(
                    uid=f"{block.uid}.c{len(cells) + 1}",
                    page=block.page,
                    bbox=part.bbox,
                    lines=[part],
                    role=BlockRole.TABLE,
                    reason="table cell",
                )
            )
    return cells


def split_line(line: Line, gap: float = _CELL_GAP) -> list[Line]:
    """Split a line at horizontal gaps wider than ``gap`` font sizes."""
    limit = gap * line.size
    groups: list[list[tuple[Span, Char]]] = [[]]
    last_x1: float | None = None
    for span in line.spans:
        for ch in span.chars:
            if not ch.c.isspace():
                if last_x1 is not None and ch.bbox.x0 - last_x1 > limit and groups[-1]:
                    groups.append([])
                last_x1 = ch.bbox.x1
            groups[-1].append((span, ch))
    if len(groups) == 1:
        return [line]
    parts: list[Line] = []
    for group in groups:
        spans = _spans(group)
        box = union_all(span.bbox for span in spans)
        if spans and box is not None:
            parts.append(Line(spans=spans, bbox=box, direction=line.direction, wmode=line.wmode))
    return parts


def _spans(group: list[tuple[Span, Char]]) -> list[Span]:
    spans: list[Span] = []
    source: Span | None = None
    chars: list[Char] = []
    for span, ch in group:
        if span is not source:
            if source is not None and chars:
                spans.append(_sub_span(source, chars))
            source, chars = span, []
        chars.append(ch)
    if source is not None and chars:
        spans.append(_sub_span(source, chars))
    return [span for span in spans if any(not ch.c.isspace() for ch in span.chars)]


def _sub_span(span: Span, chars: list[Char]) -> Span:
    box = union_all(ch.bbox for ch in chars if not ch.c.isspace()) or span.bbox
    return Span(
        font=span.font,
        size=span.size,
        flags=span.flags,
        color=span.color,
        bbox=box,
        baseline=span.baseline,
        ascender=span.ascender,
        descender=span.descender,
        chars=list(chars),
        style=span.style,
    )


def _breaks(previous: Line, line: Line, list_mode: bool) -> bool:
    a, b = previous.size, line.size
    if min(a, b) > 0 and max(a, b) / min(a, b) > 1.15:
        return True
    if line.bbox.y0 - previous.bbox.y1 > 0.9 * min(a, b):
        return True
    if _all_bold(previous) and not _all_bold(line) and len(previous.text.strip()) < 90:
        return True
    return list_mode and bool(LIST_MARKER.match(line.text))


def _all_bold(line: Line) -> bool:
    visible = [span for span in line.spans if span.text.strip()]
    return bool(visible) and all(span.style.bold for span in visible)
