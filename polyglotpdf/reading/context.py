"""The context of a passage, for the reading companion.

Given a selection on the page text (or a whole page), gather what an AI model needs
to talk about it precisely: the document title and authors, the section, the
paragraph holding the passage (joined across columns and pages, like the
translation units) and the running text right before and after it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from ..analysis.flow import MAX_BLOCKS, continues
from ..errors import ConfigError
from ..model import BlockRole
from .index import DocumentIndex
from .text import TextBlock, join_lines

#: Page furniture and figure labels are never part of the context.
_IGNORED = frozenset(
    {BlockRole.HEADER_FOOTER, BlockRole.NON_TEXT, BlockRole.ROTATED, BlockRole.FIGURE_TEXT}
)
#: Notes and floats interrupt the running text: they count only when selected.
_ASIDES = frozenset({BlockRole.FOOTNOTE, BlockRole.CAPTION, BlockRole.TABLE})
_NOT_RUNNING = _IGNORED | _ASIDES
#: Characters of running text before and after the passage, per context size.
CONTEXT_SIZES = {"short": (1200, 600), "medium": (3000, 1500), "long": (8000, 4000)}
MAX_SELECTION = 8000
MAX_CURRENT = 8000
_PAGES_BACK = 4
_PAGES_AHEAD = 3
_MAX_SPAN = 3  # pages a selection may cover

Position = tuple[int, int]  # (page, block number)


@dataclass(frozen=True, slots=True, order=True)
class Anchor:
    """A position in the page text: 0-based page and code-point offset."""

    page: int
    offset: int


@dataclass(frozen=True, slots=True)
class PassageContext:
    title: str
    authors: str | None
    section: tuple[str, ...]
    page: int  # 0-based page of the passage start
    page_label: str
    page_count: int
    selection: str  # empty when the reader asks about the whole page
    current: str  # the paragraph(s) holding the passage, or the whole page
    before: str
    after: str
    start: Anchor
    end: Anchor

    @property
    def whole_page(self) -> bool:
        return not self.selection

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["section"] = list(self.section)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PassageContext:
        values = dict(data)
        values["section"] = tuple(values.get("section") or ())
        values["start"] = Anchor(**values["start"])
        values["end"] = Anchor(**values["end"])
        return cls(**values)


def build_context(
    index: DocumentIndex,
    start: Anchor,
    end: Anchor | None = None,
    *,
    size: str = "medium",
) -> PassageContext:
    """Context of the passage ``[start, end)``; without ``end``, of the page of ``start``."""
    if size not in CONTEXT_SIZES:
        choices = ", ".join(CONTEXT_SIZES)
        raise ConfigError(f"Unknown context size {size!r}; choose one of {choices}")
    before_limit, after_limit = CONTEXT_SIZES[size]
    start = _clamp(index, start)
    selection = ""
    if end is not None:
        end = _clamp(index, end)
        start, end = min(start, end), max(start, end)
        if end.page - start.page >= _MAX_SPAN:
            last_page = start.page + _MAX_SPAN - 1
            end = Anchor(last_page, len(index.page_text(last_page).text))
        selection = _truncate(_clean(index, start, end), MAX_SELECTION)
    if not selection or end is None:  # no selection (or only whitespace): the whole page
        start = Anchor(start.page, 0)
        end = Anchor(start.page, len(index.page_text(start.page).text))

    info = index.info()
    first = _position(index, start, forward=True)
    last = _position(index, end, forward=False)
    current = before = after = ""
    if first is not None and last is not None and first <= last:
        blocks = _span(index, first, last)
        if selection:
            blocks = _extend_paragraph(index, blocks)
        current = _window(_paragraphs(index, blocks), selection, MAX_CURRENT)
        before = _gather(index, blocks[0], before_limit, forward=False)
        after = _gather(index, blocks[-1], after_limit, forward=True)
    return PassageContext(
        title=info.title,
        authors=info.authors,
        section=index.section_at(start.page, start.offset),
        page=start.page,
        page_label=index.page_label(start.page),
        page_count=index.page_count,
        selection=selection,
        current=current,
        before=before,
        after=after,
        start=start,
        end=end,
    )


# ---------------------------------------------------------------------- navigation
def _clamp(index: DocumentIndex, anchor: Anchor) -> Anchor:
    page = min(max(anchor.page, 0), index.page_count - 1)
    length = len(index.page_text(page).text)
    return Anchor(page, min(max(anchor.offset, 0), length))


def _block(index: DocumentIndex, position: Position) -> TextBlock:
    page, number = position
    return index.page_text(page).blocks[number]


def _next(index: DocumentIndex, position: Position) -> Position | None:
    page, number = position
    while True:
        number += 1
        if number < len(index.page_text(page).blocks):
            return page, number
        page, number = page + 1, -1
        if page >= index.page_count:
            return None


def _previous(index: DocumentIndex, position: Position) -> Position | None:
    page, number = position
    while True:
        number -= 1
        if number >= 0:
            return page, number
        page -= 1
        if page < 0:
            return None
        number = len(index.page_text(page).blocks)


def _position(index: DocumentIndex, anchor: Anchor, *, forward: bool) -> Position | None:
    text = index.page_text(anchor.page)
    number = text.locate(anchor.offset, forward=forward)
    if number is not None:
        return anchor.page, number
    if forward:
        return _next(index, (anchor.page, len(text.blocks) - 1))
    return _previous(index, (anchor.page, 0))


def _span(index: DocumentIndex, first: Position, last: Position) -> list[Position]:
    positions: list[Position] = []
    position: Position | None = first
    while position is not None and position <= last:
        positions.append(position)
        position = _next(index, position)
    kept = [p for p in positions if _block(index, p).role not in _IGNORED]
    return kept or positions


def _running(index: DocumentIndex, position: Position, *, forward: bool) -> Position | None:
    """The nearest block of running text (no furniture, notes or floats) in a direction."""
    step = _next if forward else _previous
    candidate = step(index, position)
    while candidate is not None and abs(candidate[0] - position[0]) <= 1:
        if _block(index, candidate).role not in _NOT_RUNNING:
            return candidate
        candidate = step(index, candidate)
    return None


def _joins(index: DocumentIndex, first: Position, second: Position) -> bool:
    """Is ``second`` the continuation of the paragraph ending in ``first``?"""
    a, b = _block(index, first), _block(index, second)
    return (
        a.role is BlockRole.PARAGRAPH
        and b.role is BlockRole.PARAGRAPH
        and continues([a.block], b.block)
    )


def _extend_paragraph(index: DocumentIndex, blocks: list[Position]) -> list[Position]:
    """Add the fragments of a paragraph continued in another column or page."""
    blocks = list(blocks)
    while len(blocks) < MAX_BLOCKS:
        previous = _running(index, blocks[0], forward=False)
        if previous is None or not _joins(index, previous, blocks[0]):
            break
        blocks.insert(0, previous)
    while len(blocks) < MAX_BLOCKS:
        following = _running(index, blocks[-1], forward=True)
        if following is None or not _joins(index, blocks[-1], following):
            break
        blocks.append(following)
    return blocks


def _gather(index: DocumentIndex, position: Position, limit: int, *, forward: bool) -> str:
    """Running text next to ``position``, up to about ``limit`` characters.

    Each paragraph that starts on another page is preceded by a ``[p. N]`` marker (the
    1-based page number), so the model can point the reader at "p. N" and be right.
    """
    positions: list[Position] = []
    total = 0
    pages = _PAGES_AHEAD if forward else _PAGES_BACK
    step = _next if forward else _previous
    candidate = step(index, position)
    while candidate is not None and total < limit and abs(candidate[0] - position[0]) <= pages:
        if _block(index, candidate).role not in _NOT_RUNNING:
            positions.append(candidate)
            total += len(_text(index, candidate)) + 2
        candidate = step(index, candidate)
    if not forward:
        positions.reverse()
    paragraphs = _paragraphs_on_pages(index, positions)
    # Keep whole paragraphs nearest the passage; cut the farthest one to fit.
    order = paragraphs if forward else paragraphs[::-1]
    kept: list[tuple[int, str]] = []
    size = 0
    for page, text in order:
        room = limit - size
        if room <= 0:
            break
        if len(text) > room:
            text = (
                text[:room].rsplit(" ", 1)[0] + " …"
                if forward
                else "… " + text[-room:].split(" ", 1)[-1]
            )
        kept.append((page, text))
        size += len(text) + 2
    if not forward:
        kept.reverse()
    pieces: list[str] = []
    shown: int | None = None
    for page, text in kept:
        if page != shown:
            pieces.append(page_marker(page))
            shown = page
        pieces.append(text)
    return "\n\n".join(pieces)


def page_marker(page: int) -> str:
    """How the context names a page for the model: ``[p. N]``, 1-based."""
    return f"[p. {page + 1}]"


# ---------------------------------------------------------------------- text
def _text(index: DocumentIndex, position: Position) -> str:
    page, number = position
    return index.page_text(page).paragraph(number)


def _paragraphs(index: DocumentIndex, positions: list[Position]) -> str:
    """Text of consecutive blocks, the fragments of one paragraph joined together."""
    return "\n\n".join(text for _, text in _paragraphs_on_pages(index, positions))


def _paragraphs_on_pages(index: DocumentIndex, positions: list[Position]) -> list[tuple[int, str]]:
    """``(page where it starts, text)`` of each paragraph of consecutive blocks."""
    paragraphs: list[tuple[int, str]] = []
    previous: Position | None = None
    for position in positions:
        text = _text(index, position)
        if not text:
            continue
        if paragraphs and previous is not None and _joins(index, previous, position):
            page, joined = paragraphs[-1]
            paragraphs[-1] = (page, join_lines([joined, text]))
        else:
            paragraphs.append((position[0], text))
        previous = position
    return paragraphs


def _clean(index: DocumentIndex, start: Anchor, end: Anchor) -> str:
    parts = []
    for page in range(start.page, end.page + 1):
        text = index.page_text(page)
        begin = start.offset if page == start.page else 0
        stop = end.offset if page == end.page else len(text.text)
        part = text.clean(begin, stop)
        if part:
            parts.append(part)
    return "\n\n".join(parts).strip()


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def _window(text: str, selection: str, limit: int) -> str:
    """At most ``limit`` characters of ``text``, centred on the selection."""
    if len(text) <= limit:
        return text
    probe = selection[:80]
    found = text.find(probe) if probe else -1
    centre = found + len(selection) // 2 if found >= 0 else 0
    begin = max(0, min(centre - limit // 2, len(text) - limit))
    window = text[begin : begin + limit]
    return ("… " if begin else "") + window + (" …" if begin + limit < len(text) else "")
