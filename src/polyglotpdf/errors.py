"""Exception hierarchy used across the package."""

from __future__ import annotations


class PolyglotPDFError(Exception):
    """Base class for every error raised by polyglotpdf."""


class InputError(PolyglotPDFError):
    """The input document cannot be read or is not supported."""


class Cancelled(PolyglotPDFError):
    """The caller cancelled the operation (see the ``cancel`` event of the pipeline)."""


class ConfigError(PolyglotPDFError):
    """Invalid configuration, glossary or command-line option."""


class TranslationError(PolyglotPDFError):
    """Base class for translation backend failures."""


class FatalTranslationError(TranslationError):
    """Unrecoverable backend error (bad credentials, unknown model, missing dependency).

    The pipeline aborts instead of silently leaving the document untranslated.
    """


class TransientTranslationError(TranslationError):
    """Temporary failure (network, rate limit, overload); the request may be retried."""


class BatchTooLargeError(TranslationError):
    """The response was truncated; the batch must be split into smaller requests."""


class RefusalError(TranslationError):
    """The model declined to translate the batch."""


class CompanionError(PolyglotPDFError):
    """The reading companion could not get an answer from the AI provider."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ReplyFormatError(CompanionError):
    """The model answered, but not in the JSON the tutor or the dictionary asked for.

    ``source`` names who asked (``"tutor"``, ``"dictionary"``), so an interface can say it
    in its own words; asking again usually works.
    """

    def __init__(self, source: str) -> None:
        super().__init__(f"The {source} answered in an unexpected format", retryable=True)
        self.source = source
