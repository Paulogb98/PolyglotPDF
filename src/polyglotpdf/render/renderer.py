"""Draws translated segments onto the target document.

Rendering runs in three phases over the whole document:

1. every translated segment is laid out (pure computation) through the frames
   of its blocks, which may span columns and pages; a segment that cannot be
   typeset keeps its original text untouched. Blocks of the same kind on a page
   then share one font scale, so neighbouring paragraphs look alike;
2. the inline formulas of all laid-out segments are extracted as single-formula
   vector snippets. This must finish before the first snippet is placed: MuPDF
   sizes the object map used to copy snippets into the target when it is first
   used;
3. page by page, the original glyphs of the laid-out segments are removed from
   the content stream (with the vector art of their inline formulas), and the
   translated lines that belong to that page are written, interleaved with the
   formulas so that text extraction follows the reading order.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import pymupdf

from ..config import LayoutSettings
from ..errors import Cancelled
from ..model import BBox, BlockRole, FontFamily, PageLayout, TextStyle
from ..pdf.content_filter import ElementKind, PointIndex, filter_page_content
from ..pdf.snippets import SnippetFactory, SnippetRequest
from ..segmentation.markup import PlaceholderRef, parse
from ..segmentation.segmenter import Segment, SegmentStatus
from .fonts import FontProvider
from .geometry import frame_for
from .typesetter import (
    BoxPiece,
    Frame,
    Layout,
    Piece,
    PlacedLine,
    TextPiece,
    Typesetter,
    Word,
)

log = logging.getLogger(__name__)

SNIPPET_PAD_X = 0.8
SNIPPET_PAD_Y = 1.2
_WHITESPACE = re.compile(r"(\s+)")
#: Roles whose blocks share a font scale per page (grouped with blocks of the same size).
_HARMONIZED = {
    BlockRole.PARAGRAPH: "body",
    BlockRole.LIST_ITEM: "body",
    BlockRole.CAPTION: "caption",
    BlockRole.FOOTNOTE: "footnote",
    BlockRole.REFERENCE: "reference",
}


@dataclass(slots=True)
class RenderStats:
    translated: int = 0
    failed: int = 0
    shrunk: int = 0
    overflowed: int = 0
    min_scale: float = 1.0


@dataclass(slots=True)
class _Plan:
    segment: Segment
    words: list[Word]
    frames: list[Frame]
    pages: list[int]  # page of each frame
    layout: Layout


def build_words(segment: Segment) -> list[Word]:
    """Translated markup -> words made of styled text pieces and formula boxes."""
    words: list[Word] = []
    current: list[Piece] = []

    def flush() -> None:
        if current:
            words.append(Word(list(current)))
            current.clear()

    for token in parse(segment.translation or ""):
        if isinstance(token, PlaceholderRef):
            ph = segment.placeholders.get(token.key)
            if ph is not None:
                ascent, descent = ph.baseline - ph.bbox.y0, ph.bbox.y1 - ph.baseline
                current.append(BoxPiece(ph.key, ph.bbox.width, ascent, descent))
            continue
        style = segment.style.combine(bold=token.bold, italic=token.italic)
        if token.mono:
            style = TextStyle(FontFamily.MONO, style.bold, style.italic)
        for part in _WHITESPACE.split(token.text):
            if not part:
                continue
            if part.isspace():
                flush()
            else:
                current.append(TextPiece(part, style, segment.color))
    flush()
    return words


class DocumentRenderer:
    def __init__(
        self,
        target: pymupdf.Document,
        snippets: SnippetFactory,
        fonts: FontProvider,
        typesetter: Typesetter,
        settings: LayoutSettings,
    ) -> None:
        self.target = target
        self.snippets = snippets
        self.fonts = fonts
        self.typesetter = typesetter
        self.settings = settings

    def render(
        self,
        pages: Sequence[PageLayout],
        segments: Sequence[Segment],
        *,
        on_page: Callable[[], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> RenderStats:
        stats = RenderStats()
        by_index = {page.index: page for page in pages}
        plans = [plan for segment in segments if (plan := self._plan(segment, by_index, stats))]
        self._harmonize(plans)
        snippet_pages = self._snippets(plans, stats)

        for page in pages:
            if cancel is not None and cancel.is_set():
                raise Cancelled("Rendering cancelled")
            active = [
                plan
                for plan in plans
                if plan.segment.status is SegmentStatus.TRANSLATED and page.index in plan.pages
            ]
            if active:
                target_page = self.target[page.index]
                self._erase(target_page, page.index, active)
                self._draw(target_page, page.index, active, snippet_pages)
            if on_page is not None:
                on_page()
        self._count([p for p in plans if p.segment.status is SegmentStatus.TRANSLATED], stats)
        return stats

    # ------------------------------------------------------------------ phase 1
    def _plan(
        self, segment: Segment, pages: dict[int, PageLayout], stats: RenderStats
    ) -> _Plan | None:
        if segment.status is not SegmentStatus.TRANSLATED or not segment.translation:
            return None
        try:
            words = build_words(segment)
            if not words:
                raise ValueError("empty translation")
            frames = [
                frame_for(block, segment.style, segment.size, pages[block.page], self.settings)
                for block in segment.blocks
            ]
            layout = self._layout(words, frames)
        except Exception as exc:
            self._fail(segment, f"layout error: {exc}", stats)
            return None
        return _Plan(segment, words, frames, [block.page for block in segment.blocks], layout)

    def _layout(self, words: list[Word], frames: list[Frame], max_scale: float = 1.0) -> Layout:
        return self.typesetter.layout(
            words,
            frames,
            min_scale=self.settings.min_font_scale,
            hard_min_scale=self.settings.hard_min_font_scale,
            max_scale=max_scale,
        )

    def _harmonize(self, plans: Sequence[_Plan]) -> None:
        """Give blocks of the same kind and original size on a page one common scale.

        Each block is first fitted on its own; without this step a paragraph that
        has free space below it keeps 100% while its neighbour shrinks to 80%.
        Blocks that needed less than the preferred minimum stay individually smaller.
        """
        groups: dict[tuple[int, str, float], list[_Plan]] = defaultdict(list)
        for plan in plans:
            kind = _HARMONIZED.get(plan.segment.role)
            if kind is not None:
                groups[(plan.pages[0], kind, round(plan.segment.size * 2) / 2)].append(plan)
        for group in groups.values():
            common = max(min(p.layout.scale for p in group), self.settings.min_font_scale)
            for plan in group:
                if plan.layout.scale > common + 0.005:
                    plan.layout = self._layout(plan.words, plan.frames, max_scale=common)

    # ------------------------------------------------------------------ phase 2
    def _snippets(self, plans: Sequence[_Plan], stats: RenderStats) -> dict[tuple[str, int], int]:
        by_page: dict[int, list[tuple[tuple[str, int], SnippetRequest, _Plan]]] = defaultdict(list)
        for plan in plans:
            for key, ph in plan.segment.placeholders.items():
                request = SnippetRequest(
                    points=tuple((ch.x, ch.y) for ch in ph.chars if not ch.c.isspace()),
                    clip=ph.bbox.expand(SNIPPET_PAD_X, SNIPPET_PAD_Y),
                )
                by_page[ph.page].append(((plan.segment.uid, key), request, plan))
        result: dict[tuple[str, int], int] = {}
        for page_index, entries in sorted(by_page.items()):
            try:
                numbers = self.snippets.create(page_index, [request for _, request, _ in entries])
            except Exception as exc:  # keep the original text of blocks whose formulas we lost
                for plan in {id(plan): plan for _, _, plan in entries}.values():
                    self._fail(plan.segment, f"formula extraction failed: {exc}", stats)
                continue
            result.update(
                {key: number for (key, _, _), number in zip(entries, numbers, strict=True)}
            )
        return result

    # ------------------------------------------------------------------ phase 3
    @staticmethod
    def _erase(page: pymupdf.Page, page_index: int, plans: Sequence[_Plan]) -> None:
        points = PointIndex(
            (ch.x, ch.y)
            for plan in plans
            for block in plan.segment.blocks
            if block.page == page_index
            for ch in block.chars
        )
        formula_areas = [
            ph.bbox.expand(SNIPPET_PAD_X, SNIPPET_PAD_Y)
            for plan in plans
            for ph in plan.segment.placeholders.values()
            if ph.page == page_index
        ]

        def cull(box: BBox, _kind: ElementKind) -> bool:
            return any(area.contains(box, 0.3) for area in formula_areas)

        stats = filter_page_content(
            page, remove_glyph=points.contains, cull=cull if formula_areas else None
        )
        log.debug(
            "page %d: removed %d glyphs, culled %d", page_index + 1, stats.removed, stats.culled
        )

    def _draw(
        self,
        page: pymupdf.Page,
        page_index: int,
        plans: Sequence[_Plan],
        snippet_pages: dict[tuple[str, int], int],
    ) -> None:
        for plan in plans:
            for line in plan.layout.lines:
                if plan.pages[line.frame] == page_index:
                    self._draw_line(page, plan, line, snippet_pages)

    def _draw_line(
        self,
        page: pymupdf.Page,
        plan: _Plan,
        line: PlacedLine,
        snippet_pages: dict[tuple[str, int], int],
    ) -> None:
        layout = plan.layout
        writer: pymupdf.TextWriter | None = None
        color = 0

        def flush() -> None:
            nonlocal writer
            if writer is not None:
                writer.write_text(page, color=_rgb(color))
                writer = None

        for placed in line.pieces:
            piece = placed.piece
            if isinstance(piece, BoxPiece):
                flush()  # keep the content stream in reading order
                self._place_formula(
                    page, plan.segment, piece, placed.x, line.baseline, layout.scale, snippet_pages
                )
                continue
            if writer is None or piece.color != color:
                flush()
                writer, color = pymupdf.TextWriter(page.rect), piece.color
            size = layout.size * piece.rel_size
            x = placed.x
            for font, part in self.fonts.segments(piece.text, piece.style):
                writer.append((x, line.baseline), part, font=font, fontsize=size)
                x += font.text_length(part, fontsize=size)
        flush()

    def _place_formula(
        self,
        page: pymupdf.Page,
        segment: Segment,
        piece: BoxPiece,
        x: float,
        baseline: float,
        scale: float,
        snippet_pages: dict[tuple[str, int], int],
    ) -> None:
        ph = segment.placeholders[piece.key]
        number = snippet_pages.get((segment.uid, piece.key))
        if number is None:
            return
        clip = ph.bbox.expand(SNIPPET_PAD_X, SNIPPET_PAD_Y)
        destination = pymupdf.Rect(
            x - (ph.bbox.x0 - clip.x0) * scale,
            baseline - (ph.baseline - clip.y0) * scale,
            x + (clip.x1 - ph.bbox.x0) * scale,
            baseline + (clip.y1 - ph.baseline) * scale,
        )
        page.show_pdf_page(
            destination,
            self.snippets.doc,
            number,
            clip=pymupdf.Rect(clip.as_tuple()),
            keep_proportion=False,
        )

    # ------------------------------------------------------------------ bookkeeping
    @staticmethod
    def _count(plans: Sequence[_Plan], stats: RenderStats) -> None:
        for plan in plans:
            stats.translated += 1
            if plan.layout.scale < 0.999:
                stats.shrunk += 1
                stats.min_scale = min(stats.min_scale, plan.layout.scale)
            if not plan.layout.fits:
                stats.overflowed += 1
                log.info("Segment %s overflows its area", plan.segment.uid)

    @staticmethod
    def _fail(segment: Segment, note: str, stats: RenderStats) -> None:
        log.warning("Keeping the original text of %s (%s)", segment.uid, note)
        segment.status = SegmentStatus.FAILED
        segment.note = note
        stats.failed += 1


def _rgb(color: int) -> tuple[float, float, float]:
    return ((color >> 16) & 255) / 255, ((color >> 8) & 255) / 255, (color & 255) / 255
