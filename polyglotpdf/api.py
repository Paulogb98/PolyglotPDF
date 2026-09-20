"""Entry points for applications built on polyglotpdf (desktop or web interfaces).

Everything here is safe to call from a user interface: nothing is printed, results
are plain dataclasses (``to_dict()`` gives JSON-ready data), errors are
:class:`~polyglotpdf.errors.PolyglotPDFError` subclasses, and long operations accept
a progress reporter and a cancel event. See ``docs/FEATURES.md``.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from .config import Settings
from .errors import InputError
from .pipeline import Estimate, PdfTranslator, TranslationReport, translate_pdf
from .progress import FunctionProgress, NullProgress, ProgressReporter
from .translation.engines import EngineInfo, EngineKind, get_engine, list_engines
from .translation.languages import list_languages
from .translation.registry import EngineCheck, check_engine, list_models


def page_count(path: str | Path) -> int:
    """Number of pages of a document (PDF or another format MuPDF opens)."""
    try:
        with pymupdf.open(Path(path)) as document:
            return int(document.page_count)
    except (RuntimeError, ValueError) as exc:
        raise InputError(f"Cannot open {path}: {exc}") from exc


def render_page(path: str | Path, page: int = 0, *, dpi: int = 110) -> bytes:
    """PNG image of one page (0-based), for previews and before/after comparisons."""
    try:
        with pymupdf.open(Path(path)) as document:
            if not 0 <= page < document.page_count:
                raise InputError(f"Page {page} is outside 0-{document.page_count - 1}")
            return bytes(document[page].get_pixmap(dpi=dpi).tobytes("png"))
    except (RuntimeError, ValueError) as exc:
        raise InputError(f"Cannot render {path}: {exc}") from exc


__all__ = [
    "EngineCheck",
    "EngineInfo",
    "EngineKind",
    "Estimate",
    "FunctionProgress",
    "NullProgress",
    "PdfTranslator",
    "ProgressReporter",
    "Settings",
    "TranslationReport",
    "check_engine",
    "get_engine",
    "list_engines",
    "list_languages",
    "list_models",
    "page_count",
    "render_page",
    "translate_pdf",
]
