"""Domain model shared by the extraction, analysis, segmentation and rendering stages.

The model is intentionally independent from PyMuPDF so that the analysis and
layout logic can be unit-tested with synthetic data. Coordinates follow the
PyMuPDF convention: origin at the top-left corner of the page, y grows downwards,
units are PDF points.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum


@dataclass(frozen=True, slots=True)
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float

    @classmethod
    def of(cls, values: Sequence[float]) -> BBox:
        return cls(float(values[0]), float(values[1]), float(values[2]), float(values[3]))

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return max(self.width, 0.0) * max(self.height, 0.0)

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2

    def union(self, other: BBox) -> BBox:
        return BBox(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )

    def intersection(self, other: BBox) -> BBox | None:
        x0, y0 = max(self.x0, other.x0), max(self.y0, other.y0)
        x1, y1 = min(self.x1, other.x1), min(self.y1, other.y1)
        if x1 <= x0 or y1 <= y0:
            return None
        return BBox(x0, y0, x1, y1)

    def intersects(self, other: BBox) -> bool:
        return self.intersection(other) is not None

    def contains_point(self, x: float, y: float, tol: float = 0.0) -> bool:
        return self.x0 - tol <= x <= self.x1 + tol and self.y0 - tol <= y <= self.y1 + tol

    def contains(self, other: BBox, tol: float = 0.0) -> bool:
        return (
            other.x0 >= self.x0 - tol
            and other.y0 >= self.y0 - tol
            and other.x1 <= self.x1 + tol
            and other.y1 <= self.y1 + tol
        )

    def expand(self, dx: float, dy: float | None = None) -> BBox:
        dy = dx if dy is None else dy
        return BBox(self.x0 - dx, self.y0 - dy, self.x1 + dx, self.y1 + dy)

    def overlap_x(self, other: BBox) -> float:
        return min(self.x1, other.x1) - max(self.x0, other.x0)

    def overlap_y(self, other: BBox) -> float:
        return min(self.y1, other.y1) - max(self.y0, other.y0)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


def union_all(boxes: Iterable[BBox]) -> BBox | None:
    result: BBox | None = None
    for box in boxes:
        result = box if result is None else result.union(box)
    return result


class FontFamily(StrEnum):
    SERIF = "serif"
    SANS = "sans"
    MONO = "mono"


@dataclass(frozen=True, slots=True)
class TextStyle:
    family: FontFamily = FontFamily.SERIF
    bold: bool = False
    italic: bool = False

    def combine(self, *, bold: bool = False, italic: bool = False) -> TextStyle:
        """Return a style with bold/italic added on top of this one."""
        return TextStyle(self.family, self.bold or bold, self.italic or italic)


class CharKind(Enum):
    TEXT = "text"
    SPACE = "space"
    MATH = "math"
    SCRIPT = "script"  # superscript/subscript in a text font (footnote markers, indices)


@dataclass(slots=True)
class Char:
    c: str
    x: float  # glyph origin (on the baseline)
    y: float
    bbox: BBox
    kind: CharKind = CharKind.TEXT
    run: int = -1  # id of the protected inline run (formula/script) this glyph belongs to


@dataclass(slots=True)
class Span:
    font: str
    size: float
    flags: int
    color: int  # sRGB integer, 0xRRGGBB
    bbox: BBox
    baseline: float
    ascender: float
    descender: float
    chars: list[Char]
    style: TextStyle

    @property
    def text(self) -> str:
        return "".join(ch.c for ch in self.chars)


@dataclass(slots=True)
class Line:
    spans: list[Span]
    bbox: BBox
    direction: tuple[float, float] = (1.0, 0.0)
    wmode: int = 0

    @property
    def chars(self) -> Iterator[Char]:
        for span in self.spans:
            yield from span.chars

    @property
    def text(self) -> str:
        return "".join(span.text for span in self.spans)

    @property
    def main_span(self) -> Span:
        """The span carrying most visible characters; defines the line's size and baseline."""
        return max(self.spans, key=lambda s: sum(not ch.c.isspace() for ch in s.chars))

    @property
    def baseline(self) -> float:
        return self.main_span.baseline

    @property
    def size(self) -> float:
        return self.main_span.size

    @property
    def is_horizontal(self) -> bool:
        dx, dy = self.direction
        return self.wmode == 0 and dx > 0.99 and abs(dy) < 0.01


class BlockRole(StrEnum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    TITLE = "title"
    CAPTION = "caption"
    LIST_ITEM = "list_item"
    FOOTNOTE = "footnote"
    HEADER_FOOTER = "header_footer"
    REFERENCE = "reference"
    AUTHOR = "author"
    DISPLAY_MATH = "display_math"
    FIGURE_TEXT = "figure_text"
    TABLE = "table"
    CODE = "code"
    NON_TEXT = "non_text"
    ROTATED = "rotated"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class Block:
    uid: str
    page: int
    bbox: BBox
    lines: list[Line]
    role: BlockRole = BlockRole.UNKNOWN
    reason: str = ""
    runs: dict[int, list[Char]] = field(default_factory=dict)

    @property
    def chars(self) -> Iterator[Char]:
        for line in self.lines:
            yield from line.chars

    @property
    def spans(self) -> Iterator[Span]:
        for line in self.lines:
            yield from line.spans

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    def dominant(self) -> tuple[TextStyle, float, int]:
        """Most frequent (style, size, color) among the block's text glyphs."""
        counter: Counter[tuple[TextStyle, float, int]] = Counter()
        fallback: Counter[tuple[TextStyle, float, int]] = Counter()
        for span in self.spans:
            key = (span.style, round(span.size, 1), span.color)
            for ch in span.chars:
                if ch.c.isspace():
                    continue
                fallback[key] += 1
                if ch.kind is CharKind.TEXT and ch.run < 0:
                    counter[key] += 1
        chosen = counter or fallback
        if not chosen:
            return TextStyle(), 10.0, 0
        return chosen.most_common(1)[0][0]


@dataclass(slots=True)
class PageLayout:
    index: int
    width: float
    height: float
    blocks: list[Block]
    graphics: list[BBox] = field(default_factory=list)  # figure-like vector/image regions
    obstacles: list[BBox] = field(default_factory=list)  # every drawn element that text must avoid
    scanned: bool = False


@dataclass(slots=True)
class DocumentStats:
    body_size: float = 10.0
    body_font: str = ""
    tex_body: bool = False


@dataclass(slots=True)
class DocumentLayout:
    pages: list[PageLayout]
    stats: DocumentStats = field(default_factory=DocumentStats)
    title: str | None = None

    def blocks(self) -> Iterator[Block]:
        for page in self.pages:
            yield from page.blocks

    def page(self, index: int) -> PageLayout:
        for page in self.pages:
            if page.index == index:
                return page
        raise KeyError(index)
