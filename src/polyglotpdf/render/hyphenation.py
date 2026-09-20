"""Dictionary-based hyphenation (pyphen / Hunspell patterns) for justified text."""

from __future__ import annotations

import logging
from typing import Any

from ..translation.languages import hyphenation_code

log = logging.getLogger(__name__)


class PyphenHyphenator:
    def __init__(self, dictionary: Any) -> None:
        self._dictionary = dictionary

    def split_points(self, word: str) -> list[int]:
        if len(word) < 6 or not word.isalpha():
            return []
        return [int(p) for p in self._dictionary.positions(word) if 2 <= p <= len(word) - 3]


def create_hyphenator(target_lang: str) -> PyphenHyphenator | None:
    try:
        import pyphen
    except ImportError:  # pragma: no cover - dependency is declared
        return None
    language = pyphen.language_fallback(hyphenation_code(target_lang))
    if language is None:
        log.info("No hyphenation dictionary for %s", target_lang)
        return None
    return PyphenHyphenator(pyphen.Pyphen(lang=language))
