"""Page text for reading: selectable words with offsets, and clean text for AI context.

The page text is built from the same analysis as the translation pipeline, block by
block in reading order: lines are separated by ``\\n`` and blocks by ``\\n\\n``. Every
word knows its box on the page and the range of the page text it covers (up to the
next word), so a selection made on the reader's text layer maps back to exact
offsets, blocks and paragraphs. Offsets count Unicode code points.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..model import BBox, Block, BlockRole, PageLayout, Span

LINE_BREAK = "\n"
BLOCK_BREAK = "\n\n"
_SOFT_HYPHEN = "­"
_HYPHENS = ("-", "‐", _SOFT_HYPHEN)
# Special characters are written as escapes: editors silently turn them into plain ones.
_CHAR_MAP = str.maketrans(
    {
        "ﬀ": "ff",
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "st",
        "ﬆ": "st",
        " ": " ",  # no-break space
        " ": " ",  # en space
        " ": " ",  # em space
        " ": " ",  # thin space
        " ": " ",  # narrow no-break space
        "\t": " ",
    }
)


@dataclass(frozen=True, slots=True)
class Word:
    """A selectable word: its box and the page-text range it covers (spaces after it included)."""

    bbox: BBox
    start: int
    end: int


@dataclass(slots=True)
class TextBlock:
    block: Block
    start: int
    end: int
    lines: list[tuple[int, int]]  # (start, end) of each line in the page text

    @property
    def role(self) -> BlockRole:
        return self.block.role


@dataclass(slots=True)
class PageText:
    index: int
    width: float
    height: float
    text: str
    words: list[Word]
    blocks: list[TextBlock]

    def locate(self, offset: int, *, forward: bool = True) -> int | None:
        """Number of the block holding ``offset``.

        Offsets between two blocks belong to the next block when ``forward`` (a
        selection start) and to the previous one otherwise (a selection end).
        """
        previous: int | None = None
        for number, block in enumerate(self.blocks):
            if offset < block.start:
                return number if forward else previous
            if offset < block.end or (not forward and offset == block.end):
                return number
            previous = number
        return None if forward else previous

    def clean(self, start: int = 0, end: int | None = None) -> str:
        """Readable text of ``[start, end)``: lines joined, hyphenation undone,
        blocks separated by blank lines."""
        stop = len(self.text) if end is None else end
        paragraphs = [
            text
            for block in self.blocks
            if block.end > start and block.start < stop
            if (text := self._block_text(block, start, stop))
        ]
        return "\n\n".join(paragraphs)

    def paragraph(self, number: int) -> str:
        """Readable text of one block."""
        block = self.blocks[number]
        return self._block_text(block, block.start, block.end)

    def to_layer(self) -> dict[str, Any]:
        """JSON for the reader's text layer: page size and ``[x0, y0, x1, y1, start, text]``
        per word (line breaks become spaces, so the lengths still match)."""
        return {
            "width": round(self.width, 2),
            "height": round(self.height, 2),
            "words": [
                [
                    round(w.bbox.x0, 2),
                    round(w.bbox.y0, 2),
                    round(w.bbox.x1, 2),
                    round(w.bbox.y1, 2),
                    w.start,
                    self.text[w.start : w.end].replace("\n", " "),
                ]
                for w in self.words
            ],
        }

    def _block_text(self, block: TextBlock, start: int, stop: int) -> str:
        lines = (
            self.text[max(a, start) : min(b, stop)]
            for a, b in block.lines
            if b > start and a < stop
        )
        return join_lines(lines)


def join_lines(lines: Iterable[str]) -> str:
    """Join the lines of a paragraph, undoing end-of-line hyphenation ("exam-" + "ple")."""
    result = ""
    for raw in lines:
        line = " ".join(raw.split())
        if not line:
            continue
        if not result:
            result = line
        elif (
            result.endswith(_HYPHENS)
            and len(result) >= 2
            and result[-2].isalpha()
            and line[0].islower()
        ):
            word = result.rsplit(" ", 1)[-1]
            compound = any(h in word[:-1] for h in ("-", "‐"))  # "state-of-the-" + "art"
            keep = compound and not result.endswith(_SOFT_HYPHEN)
            result = (result if keep else result[:-1]) + line
        else:
            result += " " + line
    return result


def build_page_text(layout: PageLayout) -> PageText:
    pieces: list[str] = []
    starts: list[tuple[BBox, int]] = []  # (box, start) of each selectable word
    blocks: list[TextBlock] = []
    offset = 0

    for block in layout.blocks:
        if blocks:
            pieces.append(BLOCK_BREAK)
            offset += len(BLOCK_BREAK)
        block_start = offset
        lines: list[tuple[int, int]] = []
        for number, line in enumerate(block.lines):
            if number:
                pieces.append(LINE_BREAK)
                offset += len(LINE_BREAK)
            line_start = offset
            selectable = line.is_horizontal
            box: BBox | None = None
            word_start = offset
            for span in line.spans:
                top, bottom = _extent(span)
                for ch in span.chars:
                    text = ch.c.translate(_CHAR_MAP)
                    if not text:
                        continue
                    if text.isspace():
                        if box is not None and selectable:
                            starts.append((box, word_start))
                        box = None
                    else:
                        # Horizontal extent of the glyph, vertical extent of the line box:
                        # every word of a line gets the same height.
                        left, right = (
                            (ch.bbox.x0, ch.bbox.x1) if ch.bbox.width > 0 else (ch.x, ch.x)
                        )
                        glyph = BBox(left, top, right, bottom)
                        if box is None:
                            box, word_start = glyph, offset
                        else:
                            box = box.union(glyph)
                    pieces.append(text)
                    offset += len(text)
            if box is not None and selectable:
                starts.append((box, word_start))
            lines.append((line_start, offset))
        blocks.append(TextBlock(block, block_start, offset, lines))

    text = "".join(pieces)
    words = [
        Word(box, start, starts[number + 1][1] if number + 1 < len(starts) else len(text))
        for number, (box, start) in enumerate(starts)
    ]
    return PageText(layout.index, layout.width, layout.height, text, words, blocks)


def _extent(span: Span) -> tuple[float, float]:
    """Top and bottom of a span's line box, from the font's ascender and descender."""
    ascender = span.ascender if span.ascender > 0 else 0.8
    descender = span.descender if span.descender < 0 else -0.2
    return span.baseline - ascender * span.size, span.baseline - descender * span.size
