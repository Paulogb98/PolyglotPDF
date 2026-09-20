"""Opening input documents and parsing page ranges."""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from ..errors import ConfigError, InputError

#: Formats MuPDF can open and convert to PDF before translation.
CONVERTIBLE = frozenset({".epub", ".xps", ".oxps", ".fb2", ".mobi", ".cbz"})
_RANGE = re.compile(r"^\s*(\d*)\s*(-)?\s*(\d*)\s*$")


def load_pdf_bytes(path: str | Path) -> bytes:
    """Read a PDF (or convert a supported e-book format) into PDF bytes."""
    file = Path(path)
    if not file.is_file():
        raise InputError(f"File not found: {file}")
    suffix = file.suffix.lower()
    try:
        if suffix == ".pdf":
            return file.read_bytes()
        if suffix in CONVERTIBLE:
            with pymupdf.open(file) as document:
                return bytes(document.convert_to_pdf())
    except (RuntimeError, ValueError) as exc:  # pymupdf.FileDataError derives from RuntimeError
        raise InputError(f"Cannot open {file}: {exc}") from exc
    supported = ", ".join(sorted({".pdf", *CONVERTIBLE}))
    raise InputError(f"Unsupported file type {suffix!r}; supported: {supported}")


def open_pdf(data: bytes) -> pymupdf.Document:
    """Open PDF bytes and normalise page rotation so all coordinates are upright."""
    try:
        document = pymupdf.open("pdf", data)
    except (RuntimeError, ValueError) as exc:
        raise InputError(f"Invalid PDF: {exc}") from exc
    if document.needs_pass:
        document.close()
        raise InputError("The PDF is password protected")
    if document.page_count == 0:
        document.close()
        raise InputError("The PDF has no pages")
    for number in range(document.page_count):
        page = document[number]
        if page.rotation:
            page.remove_rotation()
    return document


def parse_page_range(spec: str | None, page_count: int) -> list[int]:
    """Parse ``"1-3,7,10-"`` (1-based, inclusive) into sorted 0-based page indexes."""
    if spec is None or not spec.strip():
        return list(range(page_count))
    pages: set[int] = set()
    for part in spec.split(","):
        if not part.strip():
            continue
        match = _RANGE.match(part)
        if match is None or not (match.group(1) or match.group(3)):
            raise ConfigError(f"Invalid page range: {part.strip()!r}")
        start = int(match.group(1)) if match.group(1) else 1
        open_end = int(match.group(3)) if match.group(3) else page_count
        end = open_end if match.group(2) else start
        if start < 1 or end > page_count or start > end:
            raise ConfigError(f"Page range {part.strip()!r} is outside 1-{page_count}")
        pages.update(range(start - 1, end))
    return sorted(pages)
