"""Inline markup exchanged with translation engines.

Source text sent for translation contains two kinds of markup:

* placeholders ``{v1}``, ``{v2}``... standing for inline formulas, symbols and
  super/subscripts, which are drawn from the original glyphs;
* style tags ``<b>...</b>``, ``<i>...</i>`` and ``<c>...</c>`` marking bold, italic
  and monospaced words.

Engines are asked to keep both. This module parses translated text back into
styled runs, validates placeholders and repairs harmless deviations (extra
spaces inside placeholders, duplicated or unexpected placeholders).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

PLACEHOLDER_RE = re.compile(r"\{\s*[vV]\s*(\d+)\s*\}")
TAG_RE = re.compile(r"<\s*(/?)\s*([bicBIC])\s*>")
_TOKEN_RE = re.compile(rf"{PLACEHOLDER_RE.pattern}|{TAG_RE.pattern}")
#: Zero-width characters, word joiner, BOM and soft hyphen sometimes emitted by engines.
_INVISIBLE = re.compile("[​-‏⁠﻿­]")


def placeholder(key: int) -> str:
    return f"{{v{key}}}"


@dataclass(frozen=True, slots=True)
class TextRun:
    text: str
    bold: bool = False
    italic: bool = False
    mono: bool = False


@dataclass(frozen=True, slots=True)
class PlaceholderRef:
    key: int


Token = TextRun | PlaceholderRef


def parse(markup: str) -> list[Token]:
    """Split markup into styled text runs and placeholder references.

    Unbalanced tags are tolerated: stray closing tags are ignored and styles left
    open simply extend to the end of the text.
    """
    tokens: list[Token] = []
    depth = {"b": 0, "i": 0, "c": 0}
    pos = 0

    def emit(text: str) -> None:
        if text:
            tokens.append(TextRun(text, depth["b"] > 0, depth["i"] > 0, depth["c"] > 0))

    for match in _TOKEN_RE.finditer(markup):
        emit(markup[pos : match.start()])
        pos = match.end()
        if match.group(1) is not None:
            tokens.append(PlaceholderRef(int(match.group(1))))
            continue
        tag = match.group(3).lower()
        depth[tag] = max(0, depth[tag] + (-1 if match.group(2) == "/" else 1))
    emit(markup[pos:])
    return tokens


def placeholder_keys(markup: str) -> list[int]:
    return [int(m.group(1)) for m in PLACEHOLDER_RE.finditer(markup)]


def strip_tags(markup: str) -> str:
    return TAG_RE.sub("", markup)


@dataclass(frozen=True, slots=True)
class Validation:
    missing: frozenset[int]
    duplicated: frozenset[int]
    unexpected: frozenset[int]

    @property
    def ok(self) -> bool:
        return not (self.missing or self.duplicated or self.unexpected)


def validate(markup: str, expected: set[int]) -> Validation:
    counts = Counter(placeholder_keys(markup))
    return Validation(
        missing=frozenset(expected - counts.keys()),
        duplicated=frozenset(k for k, n in counts.items() if n > 1 and k in expected),
        unexpected=frozenset(counts.keys() - expected),
    )


def repair(markup: str, expected: set[int]) -> str | None:
    """Normalise a translation; return ``None`` if placeholders were lost.

    Duplicated placeholders keep their first occurrence, unknown ones are dropped,
    whitespace inside placeholders is normalised and invisible characters removed.
    """
    if not markup.strip():
        return None
    seen: set[int] = set()

    def fix(match: re.Match[str]) -> str:
        key = int(match.group(1))
        if key not in expected or key in seen:
            return ""
        seen.add(key)
        return placeholder(key)

    fixed = PLACEHOLDER_RE.sub(fix, markup)
    if seen != expected:
        return None
    fixed = _INVISIBLE.sub("", fixed)
    return re.sub(r"[ \t]{2,}", " ", fixed).strip()


def visible_text(markup: str) -> str:
    """Text without placeholders and tags: is there anything left to translate?"""
    return PLACEHOLDER_RE.sub(" ", strip_tags(markup)).strip()
