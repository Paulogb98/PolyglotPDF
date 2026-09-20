"""Character-level detection of inline mathematics and super/subscripts.

Every glyph gets a :class:`~polyglotpdf.model.CharKind`. Consecutive math and
script glyphs, together with the brackets, digits and operators glued to them,
form *runs*: each run later becomes one placeholder whose original vector glyphs
are re-drawn next to the translated text.
"""

from __future__ import annotations

import unicodedata
from itertools import pairwise

from ..model import Block, Char, CharKind, DocumentStats, Span
from .fonts import is_math_font, is_tex_text_font

_OPEN = frozenset("([{⟨")
_CLOSE = frozenset(")]}⟩")
_OPERATORS = frozenset("+-−=<>/*^_|~×·÷±∓≤≥≠≈∼")
_PRIMES = frozenset("'′″‴")
_BRIDGE_PUNCT = frozenset(",.;:")
_LETTERLIKE = frozenset("ℝℕℤℚℂℙℓℏℵ∂∇∞")
_MATH_RANGES = (
    (0x2190, 0x21FF),  # arrows
    (0x2200, 0x22FF),  # mathematical operators
    (0x27C0, 0x27EF),  # miscellaneous mathematical symbols A
    (0x2980, 0x29FF),  # miscellaneous mathematical symbols B
    (0x2A00, 0x2AFF),  # supplemental mathematical operators
    (0x1D400, 0x1D7FF),  # mathematical alphanumeric symbols
)
_GREEK_SYMBOLS = frozenset("ϑϕϖϰϱϵ")


def is_neutral(c: str) -> bool:
    """Characters that belong to a formula only when attached to one."""
    return (
        c.isdigit()
        or c in _OPEN
        or c in _CLOSE
        or c in _OPERATORS
        or c in _PRIMES
        or c in _BRIDGE_PUNCT
    )


class MathDetector:
    def __init__(
        self, stats: DocumentStats, *, greek_is_math: bool = True, max_bridge: int = 8
    ) -> None:
        self.stats = stats
        self.greek_is_math = greek_is_math
        self.max_bridge = max_bridge

    def annotate(self, block: Block) -> None:
        """Set ``kind``/``run`` on every glyph of the block and fill ``block.runs``."""
        block.runs.clear()
        next_run = 0
        for line in block.lines:
            if not line.spans:
                continue
            main = line.main_span
            for span in line.spans:
                span_kind = self.span_kind(span, main.size, main.baseline)
                for ch in span.chars:
                    ch.run = -1
                    if ch.c.isspace() or not ch.c:
                        ch.kind = CharKind.SPACE
                    elif span_kind is not CharKind.TEXT:
                        ch.kind = span_kind
                    elif self.is_math_char(ch.c):
                        ch.kind = CharKind.MATH
                    else:
                        ch.kind = CharKind.TEXT
            next_run = self._form_runs(list(line.chars), block, next_run)

    def span_kind(self, span: Span, line_size: float, line_baseline: float) -> CharKind:
        if is_math_font(span.font):
            return CharKind.MATH
        if is_tex_text_font(span.font) and not self.stats.tex_body:
            # Computer Modern in a document whose body uses another font: math mode.
            return CharKind.MATH
        if line_size > 0 and span.size < 0.85 * line_size:
            shift = line_baseline - span.baseline
            if abs(shift) > 0.12 * line_size or span.flags & 1:
                return CharKind.SCRIPT
        return CharKind.TEXT

    def is_math_char(self, c: str) -> bool:
        code = ord(c[0])
        if code < 128:
            return False  # ASCII operators are neutral: they join formulas but do not start one
        if c in _LETTERLIKE:
            return True
        if any(low <= code <= high for low, high in _MATH_RANGES):
            return True
        if unicodedata.category(c[0]) == "Sm":
            return True
        return self.greek_is_math and (0x0391 <= code <= 0x03C9 or c in _GREEK_SYMBOLS)

    def _form_runs(self, chars: list[Char], block: Block, next_run: int) -> int:
        n = len(chars)
        core = [ch.kind in (CharKind.MATH, CharKind.SCRIPT) for ch in chars]
        if not any(core):
            return next_run

        # 1. Absorb neutral characters glued to a formula: "(x)", "3×3", "x′".
        changed = True
        while changed:
            changed = False
            for i, ch in enumerate(chars):
                if core[i] or ch.kind is not CharKind.TEXT:
                    continue
                c = ch.c
                glued_right = (
                    i + 1 < n and core[i + 1] and (c in _OPEN or c.isdigit() or c in _OPERATORS)
                )
                glued_left = (
                    i > 0
                    and core[i - 1]
                    and (c in _CLOSE or c.isdigit() or c in _OPERATORS or c in _PRIMES)
                )
                if glued_right or glued_left:
                    core[i] = changed = True

        # 2. Bridge short gaps made only of spaces and neutral characters: "x, y", "F(x) := H(x)".
        positions = [i for i, flag in enumerate(core) if flag]
        for a, b in pairwise(positions):
            gap = chars[a + 1 : b]
            if not gap or len(gap) > self.max_bridge:
                continue
            if all(
                ch.kind is CharKind.SPACE or (ch.kind is CharKind.TEXT and is_neutral(ch.c))
                for ch in gap
            ):
                for k in range(a + 1, b):
                    core[k] = True

        # 3. Collect runs, leaving surrounding spaces outside.
        i = 0
        while i < n:
            if not core[i]:
                i += 1
                continue
            j = i
            while j < n and core[j]:
                j += 1
            run = chars[i:j]
            while run and run[0].kind is CharKind.SPACE:
                run = run[1:]
            while run and run[-1].kind is CharKind.SPACE:
                run = run[:-1]
            if run:
                for ch in run:
                    ch.run = next_run
                    if ch.kind is CharKind.TEXT:
                        ch.kind = CharKind.MATH
                block.runs[next_run] = run
                next_run += 1
            i = j
        return next_run
