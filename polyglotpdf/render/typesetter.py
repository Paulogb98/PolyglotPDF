"""Line breaking and fitting of translated text inside one or more linked frames.

Pure layout logic: it only needs a :class:`Measurer` for text widths, so it is
tested without PDF fonts. Text flows through the frames in order, like linked
text boxes: a paragraph that the original splits across two columns is set in
both areas. Translations are usually longer than the source; the typesetter first
tries the largest allowed size, then shrinks the text (binary search) and, below
the preferred minimum, also tightens the line spacing.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from ..model import TextStyle

_EPS = 0.01
_TEXT_ASCENT = 0.75  # of the font size, used to detect formulas taller than the text
_TEXT_DESCENT = 0.25
_HYPHENABLE = re.compile(r"(\W*)([^\W\d_]{5,})(\W*)")


class Align(Enum):
    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"
    JUSTIFY = "justify"


class Measurer(Protocol):
    def width(self, text: str, style: TextStyle, size: float) -> float: ...


class Hyphenator(Protocol):
    def split_points(self, word: str) -> Sequence[int]: ...


@dataclass(frozen=True, slots=True)
class TextPiece:
    text: str
    style: TextStyle
    color: int = 0
    rel_size: float = 1.0  # relative to the frame's base size


@dataclass(frozen=True, slots=True)
class BoxPiece:
    """An inline object with fixed metrics at scale 1 (an inline formula)."""

    key: int
    width: float
    ascent: float  # above the baseline
    descent: float  # below the baseline


Piece = TextPiece | BoxPiece


@dataclass(slots=True)
class Word:
    """Pieces glued together (no break opportunity inside), e.g. ``[formula, ","]``."""

    pieces: list[Piece]


@dataclass(frozen=True, slots=True)
class Frame:
    x0: float
    top: float
    width: float
    height: float
    base_size: float
    first_baseline: float  # distance from ``top`` to the first baseline at scale 1
    line_pitch: float  # baseline-to-baseline distance at scale 1
    align: Align = Align.LEFT
    first_indent: float = 0.0
    rest_indent: float = 0.0
    style: TextStyle = field(default_factory=TextStyle)


@dataclass(slots=True)
class PlacedPiece:
    piece: Piece
    x: float
    width: float


@dataclass(slots=True)
class PlacedLine:
    baseline: float
    pieces: list[PlacedPiece]
    frame: int = 0  # index of the frame the line is set in


@dataclass(slots=True)
class Layout:
    lines: list[PlacedLine]
    scale: float
    size: float
    height: float  # used height of the last frame
    fits: bool


@dataclass(slots=True)
class _Line:
    words: list[tuple[Word, float]]
    width: float  # natural width: words plus single spaces
    frame: int
    indent: float
    baseline: float
    descent: float


class Typesetter:
    def __init__(self, measurer: Measurer, hyphenator: Hyphenator | None = None) -> None:
        self.measurer = measurer
        self.hyphenator = hyphenator

    def layout(
        self,
        words: Sequence[Word],
        frames: Frame | Sequence[Frame],
        *,
        min_scale: float = 0.72,
        hard_min_scale: float = 0.5,
        max_scale: float = 1.0,
    ) -> Layout:
        """Lay ``words`` out at the largest scale in ``[hard_min_scale, max_scale]`` that fits."""
        chain = (frames,) if isinstance(frames, Frame) else tuple(frames)
        if not chain:
            raise ValueError("at least one frame is required")
        max_scale = max(min(max_scale, 1.0), hard_min_scale)
        min_scale = min(min_scale, max_scale)
        full = self._layout_at(words, chain, max_scale, 1.0)
        if full.fits:
            return full
        # Phase 1: shrink the text, keeping the original line spacing.
        found = self._search(words, chain, min_scale, max_scale, 1.0)
        if found is not None:
            return found
        # Phase 2: smaller text and slightly tighter lines, down to the hard minimum.
        found = self._search(words, chain, hard_min_scale, min_scale, 0.92)
        if found is not None:
            return found
        return self._layout_at(words, chain, hard_min_scale, 0.92)  # overflows

    # ------------------------------------------------------------------ search
    def _search(
        self,
        words: Sequence[Word],
        chain: Sequence[Frame],
        low: float,
        high: float,
        pitch_factor: float,
    ) -> Layout | None:
        best = self._layout_at(words, chain, low, pitch_factor)
        if not best.fits:
            return None
        for _ in range(8):
            middle = (low + high) / 2
            candidate = self._layout_at(words, chain, middle, pitch_factor)
            if candidate.fits:
                best, low = candidate, middle
            else:
                high = middle
        return best

    def _layout_at(
        self, words: Sequence[Word], chain: Sequence[Frame], scale: float, pitch_factor: float
    ) -> Layout:
        lines, fits = self._flow(words, chain, scale, pitch_factor)
        placed = [
            self._arrange(line, index == len(lines) - 1, chain[line.frame], scale)
            for index, line in enumerate(lines)
        ]
        if lines:
            last = lines[-1]
            height = last.baseline + last.descent - chain[last.frame].top
        else:
            height = 0.0
        return Layout(placed, scale, chain[0].base_size * scale, height, fits)

    # ------------------------------------------------------------------ flow
    def _flow(
        self, words: Sequence[Word], chain: Sequence[Frame], scale: float, pitch_factor: float
    ) -> tuple[list[_Line], bool]:
        """Break lines one by one, moving on to the next frame when one is full."""
        queue = deque(words)
        lines: list[_Line] = []
        index = 0
        fits = True
        while queue:
            frame = chain[index]
            size = frame.base_size * scale
            space = self.measurer.width(" ", frame.style, size)
            first_in_frame = not lines or lines[-1].frame != index
            indent = frame.first_indent if first_in_frame else frame.rest_indent
            available = frame.width - indent
            saved = deque(queue)
            taken, width = self._take_line(queue, available, scale, size, space)

            boxes = [p for word, _ in taken for p in word.pieces if isinstance(p, BoxPiece)]
            box_ascent = max((b.ascent * scale for b in boxes), default=0.0)
            box_descent = max((b.descent * scale for b in boxes), default=0.0)
            ascent = max(_TEXT_ASCENT * size, box_ascent)
            descent = max(_TEXT_DESCENT * size, box_descent)
            if first_in_frame:
                baseline = frame.top + max(frame.first_baseline * scale, box_ascent)
            else:  # formulas taller than the text push the lines apart
                previous = lines[-1]
                pitch = frame.line_pitch * scale * pitch_factor
                baseline = previous.baseline + max(pitch, previous.descent + ascent + 0.1 * size)

            overflows = baseline + descent > frame.top + frame.height + _EPS
            if overflows and index < len(chain) - 1:
                queue = saved  # the line starts the next frame instead
                index += 1
                continue
            if overflows or width > available + 0.5:
                fits = False
            lines.append(_Line(taken, width, index, indent, baseline, descent))
        return lines, fits

    def _take_line(
        self, queue: deque[Word], available: float, scale: float, size: float, space: float
    ) -> tuple[list[tuple[Word, float]], float]:
        current: list[tuple[Word, float]] = []
        width = 0.0
        while queue:
            word = queue.popleft()
            w = self._word_width(word, scale, size)
            needed = w if not current else width + space + w
            if needed <= available + _EPS:
                current.append((word, w))
                width = needed
                continue
            room = available - (width + space if current else 0.0)
            split = self._hyphenate(word, room, size)
            if split is None and not current:
                split = self._force_split(word, available, size)
            if split is not None:
                head, tail = split
                head_width = self._word_width(head, scale, size)
                width = head_width if not current else width + space + head_width
                current.append((head, head_width))
                queue.appendleft(tail)
            elif current:
                queue.appendleft(word)
            else:  # unbreakable and wider than the line: it overflows
                current.append((word, w))
                width = w
            break
        return current, width

    def _word_width(self, word: Word, scale: float, size: float) -> float:
        return sum(self._piece_width(piece, scale, size) for piece in word.pieces)

    def _piece_width(self, piece: Piece, scale: float, size: float) -> float:
        if isinstance(piece, TextPiece):
            return self.measurer.width(piece.text, piece.style, size * piece.rel_size)
        return piece.width * scale

    def _hyphenate(self, word: Word, room: float, size: float) -> tuple[Word, Word] | None:
        if len(word.pieces) != 1 or not isinstance(word.pieces[0], TextPiece) or room <= size:
            return None
        piece = word.pieces[0]
        text = piece.text
        candidates: list[tuple[str, str]] = []
        match = _HYPHENABLE.fullmatch(text)
        if match and self.hyphenator is not None:
            lead, core, trail = match.groups()
            for point in self.hyphenator.split_points(core):
                candidates.append((f"{lead}{core[:point]}-", f"{core[point:]}{trail}"))
        for index, ch in enumerate(text):  # break after an existing hyphen ("bem-|vindo")
            if ch == "-" and 1 < index < len(text) - 2:
                candidates.append((text[: index + 1], text[index + 1 :]))
        psize = size * piece.rel_size
        best: tuple[str, str] | None = None
        for head, tail in candidates:
            fits = self.measurer.width(head, piece.style, psize) <= room + _EPS
            if fits and (best is None or len(head) > len(best[0])):
                best = (head, tail)
        if best is None:
            return None
        return (
            Word([TextPiece(best[0], piece.style, piece.color, piece.rel_size)]),
            Word([TextPiece(best[1], piece.style, piece.color, piece.rel_size)]),
        )

    def _force_split(self, word: Word, available: float, size: float) -> tuple[Word, Word] | None:
        """Break an over-long word (URL, CJK run) at the last character that fits."""
        if len(word.pieces) != 1 or not isinstance(word.pieces[0], TextPiece):
            return None
        piece = word.pieces[0]
        text = piece.text
        if len(text) < 2:
            return None
        psize = size * piece.rel_size
        low, high = 1, len(text) - 1
        while low < high:  # largest prefix that fits
            middle = (low + high + 1) // 2
            if self.measurer.width(text[:middle], piece.style, psize) <= available + _EPS:
                low = middle
            else:
                high = middle - 1
        return (
            Word([TextPiece(text[:low], piece.style, piece.color, piece.rel_size)]),
            Word([TextPiece(text[low:], piece.style, piece.color, piece.rel_size)]),
        )

    # ------------------------------------------------------------------ placement
    def _arrange(self, line: _Line, is_last: bool, frame: Frame, scale: float) -> PlacedLine:
        size = frame.base_size * scale
        space = self.measurer.width(" ", frame.style, size)
        available = frame.width - line.indent
        x = frame.x0 + line.indent
        gap = space
        gaps = len(line.words) - 1
        slack = available - line.width
        if frame.align is Align.JUSTIFY and not is_last and gaps > 0:
            extra = slack / gaps
            if 0 < extra <= 4 * space + 1:
                gap = space + extra
        elif frame.align is Align.CENTER:
            x += max(0.0, slack / 2)
        elif frame.align is Align.RIGHT:
            x += max(0.0, slack)
        pieces: list[PlacedPiece] = []
        for word, _ in line.words:
            for piece in word.pieces:
                width = self._piece_width(piece, scale, size)
                pieces.append(PlacedPiece(piece, x, width))
                x += width
            x += gap
        return PlacedLine(line.baseline, pieces, line.frame)
