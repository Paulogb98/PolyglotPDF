"""Fonts for the translated text, with per-glyph fallback.

Defaults are MuPDF's built-in URW fonts (Nimbus Roman/Sans/Mono: Latin, Greek
and Cyrillic) and Droid Sans Fallback for CJK. Any font file can be configured
instead. Only the glyphs actually used end up in the output after subsetting.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from ..config import FontSettings
from ..errors import ConfigError
from ..model import FontFamily, TextStyle
from ..translation.languages import is_cjk

_BUILTIN: dict[tuple[FontFamily, bool, bool], str] = {
    (FontFamily.SERIF, False, False): "tiro",
    (FontFamily.SERIF, True, False): "tibo",
    (FontFamily.SERIF, False, True): "tiit",
    (FontFamily.SERIF, True, True): "tibi",
    (FontFamily.SANS, False, False): "helv",
    (FontFamily.SANS, True, False): "hebo",
    (FontFamily.SANS, False, True): "heit",
    (FontFamily.SANS, True, True): "hebi",
    (FontFamily.MONO, False, False): "cour",
    (FontFamily.MONO, True, False): "cobo",
    (FontFamily.MONO, False, True): "coit",
    (FontFamily.MONO, True, True): "cobi",
}
_FONT_FILES = frozenset({".ttf", ".otf", ".ttc", ".otc", ".pfb", ".pfa", ".cff", ".woff", ".woff2"})
_CJK = "cjk"


class FontProvider:
    """Resolves fonts by style, measures text and splits it by glyph coverage.

    Implements the :class:`~polyglotpdf.render.typesetter.Measurer` protocol.
    """

    def __init__(self, settings: FontSettings | None = None, target_lang: str = "pt-BR") -> None:
        self.settings = settings or FontSettings()
        self.cjk = is_cjk(target_lang)
        self._fonts: dict[str, pymupdf.Font] = {}
        self._glyphs: dict[tuple[int, str], bool] = {}
        self._unit_widths: dict[tuple[str, TextStyle], float] = {}
        self.missing: set[str] = set()

    def font(self, style: TextStyle) -> pymupdf.Font:
        return self._load(self._spec(style))

    def segments(self, text: str, style: TextStyle) -> list[tuple[pymupdf.Font, str]]:
        """Split ``text`` into runs drawable with a single font each."""
        primary = self.font(style)
        runs: list[tuple[pymupdf.Font, str]] = []
        current: pymupdf.Font | None = None
        buffer: list[str] = []
        for ch in text:
            font = primary
            if not ch.isspace() and not self._has(primary, ch):
                fallback = self._fallback(ch)
                if fallback is None:
                    self.missing.add(ch)
                else:
                    font = fallback
            if font is not current and buffer:
                runs.append((current, "".join(buffer)))  # type: ignore[arg-type]
                buffer = []
            current = font
            buffer.append(ch)
        if buffer:
            runs.append((current, "".join(buffer)))  # type: ignore[arg-type]
        return runs

    # ------------------------------------------------------------------ Measurer
    def width(self, text: str, style: TextStyle, size: float) -> float:
        key = (text, style)
        unit = self._unit_widths.get(key)
        if unit is None:
            unit = sum(
                font.text_length(part, fontsize=1.0) for font, part in self.segments(text, style)
            )
            self._unit_widths[key] = unit
        return unit * size

    # ------------------------------------------------------------------ internals
    def _spec(self, style: TextStyle) -> str:
        name = (
            style.family.value
            + ("_bold" if style.bold else "")
            + ("_italic" if style.italic else "")
        )
        configured = getattr(self.settings, name, None)
        if configured:
            return str(configured)
        if self.cjk:
            return _CJK
        return _BUILTIN[(style.family, style.bold, style.italic)]

    def _load(self, spec: str) -> pymupdf.Font:
        font = self._fonts.get(spec)
        if font is None:
            path = Path(spec)
            try:
                if path.suffix.lower() in _FONT_FILES:
                    font = pymupdf.Font(fontfile=str(path))
                else:
                    font = pymupdf.Font(spec)
            except Exception as exc:
                raise ConfigError(f"Cannot load font {spec!r}: {exc}") from exc
            self._fonts[spec] = font
        return font

    def _has(self, font: pymupdf.Font, ch: str) -> bool:
        key = (id(font), ch)
        known = self._glyphs.get(key)
        if known is None:
            known = self._glyphs[key] = bool(font.has_glyph(ord(ch)))
        return known

    def _fallback(self, ch: str) -> pymupdf.Font | None:
        specs = [self.settings.fallback] if self.settings.fallback else []
        specs.append(_CJK)
        for spec in specs:
            font = self._load(spec)
            if self._has(font, ch):
                return font
        return None
