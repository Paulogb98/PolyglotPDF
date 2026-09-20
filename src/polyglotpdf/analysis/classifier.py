"""Assigns a role to every block: paragraph, heading, formula, reference, figure label...

Roles decide what is sent for translation (every kind of text, see
:func:`translatable_roles`), how blocks are grouped into paragraphs across columns
and how the renderer harmonises font sizes. Every decision records a short
reason, visible with ``polyglotpdf inspect``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import ContentSettings
from ..model import (
    Block,
    BlockRole,
    CharKind,
    DocumentLayout,
    DocumentStats,
    FontFamily,
    PageLayout,
)
from .structure import LIST_MARKER

_WORD = re.compile(r"[^\W\d_]{2,}")
_CAPTION = re.compile(
    r"^\s*(?:fig(?:ure)?|tab(?:le)?|algorithm|listing|scheme|chart|plate|figura|tabela|quadro|"
    r"gr[aá]fico)\.?\s*[A-Z]?\d+[a-z]?\b",
    re.IGNORECASE,
)
_REFERENCES = re.compile(
    r"^\s*(?:\d+\.?\s*|[IVX]+\.\s*)?(?:references|bibliography|works cited|literature cited|"
    r"refer[eê]ncias(?: bibliogr[aá]ficas)?|bibliografia|r[ée]f[ée]rences|literaturverzeichnis|"
    r"bibliograf[ií]a)\s*$",
    re.IGNORECASE,
)
_ABSTRACT = re.compile(r"^\s*(?:abstract|resumo|summary|resumen|résumé|zusammenfassung)\b", re.I)
_BIB_ENTRY = re.compile(r"^\s*\[\d{1,4}\]\s+\S.*\b(?:1[5-9]|20)\d{2}\b", re.DOTALL)
_EMAIL = re.compile(r"@[\w-]+\.[\w.-]+")

#: Every role that carries text. Formulas, numbers, rotated text and (by default)
#: code listings are left as they are.
TEXT_ROLES = frozenset(
    {
        BlockRole.PARAGRAPH,
        BlockRole.HEADING,
        BlockRole.TITLE,
        BlockRole.CAPTION,
        BlockRole.LIST_ITEM,
        BlockRole.FOOTNOTE,
        BlockRole.HEADER_FOOTER,
        BlockRole.REFERENCE,
        BlockRole.AUTHOR,
        BlockRole.FIGURE_TEXT,
        BlockRole.TABLE,
    }
)


@dataclass(slots=True)
class BlockFeatures:
    chars: int  # visible glyphs
    letters: int  # letters outside formulas
    words: int  # words (2+ letters) outside formulas
    math_chars: int
    size: float
    bold: float  # share of bold glyphs
    mono: float  # share of monospaced glyphs
    lines: int
    text: str  # whole block on one line


def features(block: Block) -> BlockFeatures:
    total = letters = math = bold = mono = 0
    prose: list[str] = []
    for line in block.lines:
        for span in line.spans:
            for ch in span.chars:
                if ch.kind is CharKind.SPACE:
                    prose.append(" ")
                    continue
                total += 1
                bold += span.style.bold
                mono += span.style.family is FontFamily.MONO
                if ch.run >= 0 or ch.kind in (CharKind.MATH, CharKind.SCRIPT):
                    math += 1
                    prose.append(" ")
                    continue
                letters += ch.c.isalpha()
                prose.append(ch.c)
        prose.append(" ")
    _, size, _ = block.dominant()
    return BlockFeatures(
        chars=total,
        letters=letters,
        words=len(_WORD.findall("".join(prose))),
        math_chars=math,
        size=size,
        bold=bold / total if total else 0.0,
        mono=mono / total if total else 0.0,
        lines=len(block.lines),
        text=" ".join(block.text.split()),
    )


def translatable_roles(content: ContentSettings) -> set[BlockRole]:
    roles = set(TEXT_ROLES)
    if content.translate_code:
        roles.add(BlockRole.CODE)
    return roles


class BlockClassifier:
    def __init__(self, stats: DocumentStats) -> None:
        self.stats = stats

    def classify(self, layout: DocumentLayout) -> None:
        for page in layout.pages:
            for block in page.blocks:
                if block.role is BlockRole.UNKNOWN:
                    block.role, block.reason = self._classify(block, page)
                elif block.role is BlockRole.TABLE:
                    block.role, block.reason = self._classify_cell(block)
        self._detect_title(layout)
        self._detect_authors(layout)
        self._detect_references(layout)

    # ------------------------------------------------------------------ block rules
    def _classify(self, block: Block, page: PageLayout) -> tuple[BlockRole, str]:
        if any(not line.is_horizontal for line in block.lines):
            return BlockRole.ROTATED, "rotated or vertical text"
        f = features(block)
        if f.chars == 0:
            return BlockRole.NON_TEXT, "empty"
        if f.letters == 0:
            if f.math_chars:
                return BlockRole.DISPLAY_MATH, "formula without prose"
            return BlockRole.NON_TEXT, "numbers or punctuation only"
        if f.math_chars and (f.words <= 1 or (f.math_chars > 0.6 * f.chars and f.words <= 3)):
            return BlockRole.DISPLAY_MATH, "mostly mathematics"
        body = self.stats.body_size
        box = block.bbox
        footnote_zone = f.size <= 0.92 * body and box.y0 > 0.72 * page.height
        # Small monospaced text at the bottom of the page is a footnote with URLs, not code.
        if f.mono > 0.8 and not footnote_zone and (f.lines > 1 or f.words <= 3):
            return BlockRole.CODE, "monospaced text"

        in_margin = box.y1 < 0.075 * page.height or box.y0 > 0.93 * page.height
        if in_margin and f.lines <= 2 and f.words <= 15:
            return BlockRole.HEADER_FOOTER, "page margin"
        if f.words <= 8 and self._inside_figure(block, page):
            return BlockRole.FIGURE_TEXT, "inside a figure"
        if f.size < 0.8 * body and f.words <= 4 and f.lines <= 2:
            return BlockRole.FIGURE_TEXT, "small isolated label"
        if _CAPTION.match(f.text):
            return BlockRole.CAPTION, "caption prefix"
        if self._looks_like_heading(f):
            return BlockRole.HEADING, "heading style"
        if LIST_MARKER.match(f.text):
            return BlockRole.LIST_ITEM, "list marker"
        if f.size <= 0.92 * body and box.y0 > 0.72 * page.height:
            return BlockRole.FOOTNOTE, "small text at the bottom of the page"
        if _BIB_ENTRY.match(f.text):
            return BlockRole.REFERENCE, "bibliography entry"
        return BlockRole.PARAGRAPH, "prose"

    @staticmethod
    def _classify_cell(block: Block) -> tuple[BlockRole, str]:
        if any(not line.is_horizontal for line in block.lines):
            return BlockRole.ROTATED, "rotated or vertical text"
        f = features(block)
        if f.letters == 0:
            if f.math_chars:
                return BlockRole.DISPLAY_MATH, "formula in a table"
            return BlockRole.NON_TEXT, "numbers in a table"
        if f.math_chars > 0.6 * f.chars and f.words <= 2:
            return BlockRole.DISPLAY_MATH, "mostly mathematics"
        return BlockRole.TABLE, "table cell"

    def _looks_like_heading(self, f: BlockFeatures) -> bool:
        if f.lines > 3 or f.words == 0 or f.words > 18:
            return False
        if f.text.endswith((".", ",", ";")) and f.words > 8:
            return False
        larger = f.size >= 1.12 * self.stats.body_size
        return larger or (f.bold >= 0.8 and f.words <= 14)

    @staticmethod
    def _inside_figure(block: Block, page: PageLayout) -> bool:
        area = block.bbox.area
        for region in page.graphics:
            overlap = block.bbox.intersection(region.expand(2.0))
            if overlap is not None and (area == 0 or overlap.area >= 0.8 * area):
                return True
        return False

    # ------------------------------------------------------------------ document rules
    def _detect_title(self, layout: DocumentLayout) -> None:
        first = next((p for p in layout.pages if p.index == 0), None)
        if first is None:
            return
        candidates = [
            b
            for b in first.blocks
            if b.role in (BlockRole.HEADING, BlockRole.PARAGRAPH) and b.bbox.y1 < 0.5 * first.height
        ]
        if not candidates:
            return
        best = max(candidates, key=lambda b: b.dominant()[1])
        if best.dominant()[1] >= 1.3 * self.stats.body_size:
            best.role, best.reason = BlockRole.TITLE, "largest text on the first page"
            layout.title = " ".join(best.text.split())

    def _detect_authors(self, layout: DocumentLayout) -> None:
        first = next((p for p in layout.pages if p.index == 0), None)
        if first is None:
            return
        after_title = False
        for block in first.blocks:
            if block.role is BlockRole.TITLE:
                after_title = True
                continue
            if not after_title:
                continue
            f = features(block)
            if _ABSTRACT.match(f.text) or (block.role is BlockRole.PARAGRAPH and f.words > 40):
                break
            if block.role not in (
                BlockRole.PARAGRAPH,
                BlockRole.HEADING,
                BlockRole.FOOTNOTE,
                BlockRole.TABLE,
            ):
                continue
            centered = (
                abs(block.bbox.center_x - first.width / 2) < 0.05 * first.width
                and block.bbox.width < 0.75 * first.width
            )
            # Names laid out side by side are split into table cells by the structure step.
            name_cell = block.role is BlockRole.TABLE and f.words <= 12
            if _EMAIL.search(f.text) or centered or name_cell:
                block.role, block.reason = BlockRole.AUTHOR, "author block below the title"

    def _detect_references(self, layout: DocumentLayout) -> None:
        inside = False
        for block in layout.blocks():
            if block.role in (BlockRole.HEADING, BlockRole.PARAGRAPH) and len(block.lines) <= 2:
                text = " ".join(block.text.split())
                if _REFERENCES.match(text):
                    block.role, block.reason = BlockRole.HEADING, "references heading"
                    inside = True
                    continue
            if not inside:
                continue
            if block.role is BlockRole.HEADING:  # e.g. an appendix after the bibliography
                inside = False
            elif block.role in (BlockRole.PARAGRAPH, BlockRole.LIST_ITEM, BlockRole.FOOTNOTE):
                block.role, block.reason = BlockRole.REFERENCE, "inside the references section"
