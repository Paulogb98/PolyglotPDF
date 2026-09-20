"""polyglotpdf: layout-preserving translation of PDF papers and e-books.

Typical use::

    from polyglotpdf import Settings, translate_pdf

    settings = Settings()
    settings.translation.engine = "openai"      # or "google" (default), "deepl", ...
    settings.translation.api_key = "sk-..."
    report = translate_pdf("paper.pdf", settings=settings)
    print(report.output_path)

See :mod:`polyglotpdf.api` and ``docs/FEATURES.md`` for everything an interface can use.
"""

from importlib.metadata import PackageNotFoundError, version

from .api import (
    EngineCheck,
    EngineInfo,
    EngineKind,
    Estimate,
    FunctionProgress,
    NullProgress,
    PdfTranslator,
    ProgressReporter,
    Settings,
    TranslationReport,
    check_engine,
    get_engine,
    list_engines,
    list_languages,
    list_models,
    page_count,
    render_page,
    translate_pdf,
)
from .errors import Cancelled, PolyglotPDFError

try:
    __version__ = version("polyglotpdf")
except PackageNotFoundError:  # running from a source checkout without installation
    __version__ = "0.0.0"

__all__ = [
    "Cancelled",
    "EngineCheck",
    "EngineInfo",
    "EngineKind",
    "Estimate",
    "FunctionProgress",
    "NullProgress",
    "PdfTranslator",
    "PolyglotPDFError",
    "ProgressReporter",
    "Settings",
    "TranslationReport",
    "__version__",
    "check_engine",
    "get_engine",
    "list_engines",
    "list_languages",
    "list_models",
    "page_count",
    "render_page",
    "translate_pdf",
]
