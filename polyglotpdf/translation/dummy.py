"""Offline engines for tests and layout previews (no network, no cost)."""

from __future__ import annotations

import re
from collections.abc import Sequence

from .base import TranslationContext, TranslationRequest, Translator

_MARKUP = re.compile(r"(\{\s*[vV]\s*\d+\s*\}|<\s*/?\s*[bicBIC]\s*>)")
_ACCENTS = str.maketrans("aeiouAEIOUcnsyzCNSYZ", "àéîöûÀÉÎÖÛçñšýžÇÑŠÝŽ")
_WORD = re.compile(r"[^\W\d_]{4,}")


class EchoTranslator(Translator):
    """Returns the source unchanged: re-typesets the document without translating it."""

    name = "echo"

    def fingerprint(self) -> str:
        return "echo/1"

    def translate_batch(
        self, requests: Sequence[TranslationRequest], context: TranslationContext
    ) -> list[str | None]:
        return [r.text for r in requests]


class PseudoTranslator(Translator):
    """Pseudo-localisation: accents letters and lengthens words by about 30%.

    Portuguese or Spanish translations are typically 15-30% longer than English,
    so this engine is a cheap way to stress-test the layout engine.
    """

    name = "pseudo"

    def __init__(self, expansion: float = 0.3) -> None:
        self.expansion = expansion

    def fingerprint(self) -> str:
        return f"pseudo/{self.expansion}"

    def translate_batch(
        self, requests: Sequence[TranslationRequest], context: TranslationContext
    ) -> list[str | None]:
        return [self._pseudo(r.text) for r in requests]

    def _pseudo(self, text: str) -> str:
        parts = _MARKUP.split(text)
        for i in range(0, len(parts), 2):  # even indexes are plain text
            parts[i] = _WORD.sub(self._stretch, parts[i]).translate(_ACCENTS)
        return "".join(parts)

    def _stretch(self, match: re.Match[str]) -> str:
        word = match.group(0)
        extra = max(1, round(len(word) * self.expansion))
        return word + word[-1] * extra
