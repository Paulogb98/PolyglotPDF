"""PolyglotPDF Reader: a desktop/web application built on the core.

A local web server (FastAPI) serves the reader interface and its API: the library,
the page images and text layer, translations run in the background and the reading
companion. The launcher opens it in a native window (pywebview, when installed), in
a Chromium browser in app mode, or in the default browser. Requires the ``app``
extra: ``pip install polyglotpdf[app]``.
"""

from .config import AppConfig, default_data_dir

__all__ = ["AppConfig", "default_data_dir"]
