"""Translator interface implemented by every engine."""

from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from .glossary import Glossary


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    uid: str
    text: str
    role: str = "paragraph"


@dataclass(frozen=True, slots=True)
class TranslationContext:
    source_lang: str
    target_lang: str
    glossary: Glossary = field(default_factory=Glossary)
    document_title: str | None = None
    strict: bool = False  # retry mode: a previous answer broke the placeholders

    def as_strict(self) -> TranslationContext:
        return replace(self, strict=True)


class Translator(abc.ABC):
    """A translation engine. Implementations must be safe to call from several threads."""

    name: str = "base"
    max_batch_items: int = 40
    max_batch_chars: int = 7000
    #: Whether the engine applies the glossary (engines driven by instructions do).
    supports_glossary: bool = False
    #: Upper bound for simultaneous requests (``None``: limited only by the settings).
    max_concurrency: int | None = None

    @abc.abstractmethod
    def fingerprint(self) -> str:
        """Identifies engine, model and prompt version; part of the cache key."""

    @abc.abstractmethod
    def translate_batch(
        self, requests: Sequence[TranslationRequest], context: TranslationContext
    ) -> list[str | None]:
        """Translate a batch, returning one entry per request (``None`` if that item failed).

        Batch-level problems are signalled with the exceptions in :mod:`polyglotpdf.errors`.
        """

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release network resources."""
