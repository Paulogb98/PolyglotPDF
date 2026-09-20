"""Turn blocks into translation segments.

A segment is one logical unit of text: usually a block, or several blocks when a
paragraph continues in another column or page (see
:mod:`polyglotpdf.analysis.flow`). Its source text keeps the whole content:

* lines and blocks are joined, with end-of-line hyphenation undone;
* inline formulas, symbols and super/subscripts become placeholders ``{vN}``,
  later drawn from the original vector glyphs;
* bold, italic and monospaced words that differ from the dominant style get
  ``<b>``, ``<i>`` and ``<c>`` tags.

Everything else (names, titles, URLs, code words...) is sent to the translator.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import Enum

from ..model import BBox, Block, BlockRole, Char, FontFamily, Line, Span, TextStyle, union_all
from .markup import placeholder, visible_text

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
_SOFT_HYPHEN = "­"
_HYPHENS = ("-", "‐", _SOFT_HYPHEN)
_SPACES = re.compile(r"\s+")


@dataclass(slots=True)
class Placeholder:
    """An inline formula, symbol or super/subscript, drawn from the original glyphs."""

    key: int
    text: str
    page: int  # page where the glyphs are on the original document
    bbox: BBox  # ink box of the glyphs
    baseline: float  # baseline of the source line
    chars: list[Char] = field(default_factory=list)


class SegmentStatus(Enum):
    PENDING = "pending"
    TRANSLATED = "translated"
    FAILED = "failed"


@dataclass(slots=True)
class Segment:
    uid: str
    blocks: list[Block]
    source: str
    placeholders: dict[int, Placeholder]
    style: TextStyle
    size: float
    color: int
    translation: str | None = None
    status: SegmentStatus = SegmentStatus.PENDING
    note: str = ""

    @property
    def block(self) -> Block:
        return self.blocks[0]

    @property
    def page(self) -> int:
        return self.blocks[0].page

    @property
    def role(self) -> BlockRole:
        return self.blocks[0].role

    @property
    def merged(self) -> bool:
        """True when the segment spans several blocks (columns or pages)."""
        return len(self.blocks) > 1

    @property
    def chars(self) -> Iterator[Char]:
        for block in self.blocks:
            yield from block.chars


@dataclass(slots=True)
class _Piece:
    text: str
    style: TextStyle
    color: int
    placeholder: Placeholder | None = None


class Segmenter:
    def build(self, blocks: Block | Sequence[Block]) -> Segment | None:
        group = [blocks] if isinstance(blocks, Block) else list(blocks)
        if not group:
            return None
        style, size, color = group[0].dominant()
        pieces: list[_Piece] = []
        seen: set[tuple[int, int]] = set()
        started = False
        for index, block in enumerate(group):
            for line in block.lines:
                if started:
                    self._join(pieces, line, style, color)
                started = True
                for span in line.spans:
                    for ch in span.chars:
                        if ch.run >= 0:
                            if (index, ch.run) not in seen:
                                seen.add((index, ch.run))
                                formula = self._placeholder(block, ch.run, line)
                                pieces.append(_Piece("", span.style, span.color, formula))
                            continue
                        self._append(pieces, ch.c.translate(_CHAR_MAP), span)

        placeholders: dict[int, Placeholder] = {}
        for piece in pieces:
            if piece.placeholder is not None:
                piece.placeholder.key = len(placeholders) + 1
                placeholders[piece.placeholder.key] = piece.placeholder

        source = self._serialize(pieces, style)
        if not re.search(r"[^\W\d_]", visible_text(source)):
            return None  # nothing but formulas, numbers or punctuation
        return Segment(group[0].uid, group, source, placeholders, style, size, color)

    # ------------------------------------------------------------------ building
    @staticmethod
    def _append(pieces: list[_Piece], text: str, span: Span) -> None:
        last = pieces[-1] if pieces else None
        if (
            last is not None
            and last.placeholder is None
            and last.style == span.style
            and last.color == span.color
        ):
            last.text += text
        else:
            pieces.append(_Piece(text, span.style, span.color))

    @staticmethod
    def _join(pieces: list[_Piece], line: Line, style: TextStyle, color: int) -> None:
        """Join two lines: undo end-of-line hyphenation or insert a space."""
        next_char = next((ch.c for ch in line.chars if not ch.c.isspace()), "")
        last = pieces[-1] if pieces else None
        if last is None or last.placeholder is not None:
            pieces.append(_Piece(" ", style, color))
            return
        stripped = last.text.rstrip()
        if (
            stripped.endswith(_HYPHENS)
            and len(stripped) >= 2
            and stripped[-2].isalpha()
            and next_char.islower()
        ):
            words = stripped.split()
            word = words[-1] if words else stripped
            compound = any(h in word[:-1] for h in ("-", "‐"))  # "state-of-the-" + "art"
            keep_hyphen = compound and not stripped.endswith(_SOFT_HYPHEN)
            last.text = stripped if keep_hyphen else stripped[:-1]
            return
        if not last.text.endswith(" "):
            last.text += " "

    @staticmethod
    def _placeholder(block: Block, run: int, line: Line) -> Placeholder:
        chars = block.runs[run]
        ink = union_all(ch.bbox for ch in chars if not ch.c.isspace() and ch.bbox.area > 0)
        if ink is None:
            ink = union_all(ch.bbox for ch in chars) or line.bbox
        return Placeholder(
            key=0,
            text="".join(ch.c for ch in chars).strip(),
            page=block.page,
            bbox=ink,
            baseline=line.baseline,
            chars=list(chars),
        )

    @staticmethod
    def _serialize(pieces: list[_Piece], base: TextStyle) -> str:
        out: list[str] = []
        for piece in pieces:
            if piece.placeholder is not None:
                out.append(placeholder(piece.placeholder.key))
                continue
            text = piece.text.replace(_SOFT_HYPHEN, "")
            bold = piece.style.bold and not base.bold
            italic = piece.style.italic and not base.italic
            mono = piece.style.family is FontFamily.MONO and base.family is not FontFamily.MONO
            core = text.strip()
            if not (bold or italic or mono) or not core:
                out.append(text)
                continue
            lead = text[: len(text) - len(text.lstrip())]
            trail = text[len(text.rstrip()) :]
            tags = [t for t, on in (("b", bold), ("i", italic), ("c", mono)) if on]
            opening = "".join(f"<{t}>" for t in tags)
            closing = "".join(f"</{t}>" for t in reversed(tags))
            out.append(f"{lead}{opening}{core}{closing}{trail}")
        source = _SPACES.sub(" ", "".join(out)).strip()
        # Merge neighbouring runs with the same style: "<i>a</i> <i>b</i>" -> "<i>a b</i>".
        for tag in ("c", "i", "b"):
            source = re.sub(rf"</{tag}>(\s*)<{tag}>", r"\1", source)
        return source
