"""Documents opened for reading: page images, text layer, outline, metadata and search.

PyMuPDF must not be used from several threads at once, while a reading application
serves page images, text layers and AI context concurrently. Every MuPDF call in this
module runs under :data:`MUPDF_LOCK` (and MuPDF objects never outlive it); the
analysed page text is plain Python and is shared freely.

Pages are analysed lazily with the translation pipeline's extraction and classifier,
using document statistics computed once from a sample of pages.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from ..analysis.classifier import BlockClassifier
from ..analysis.document import compute_stats
from ..analysis.math_detect import MathDetector
from ..analysis.structure import refine_page
from ..model import BBox, BlockRole, DocumentLayout, DocumentStats, PageLayout
from ..pdf.extractor import extract_page
from ..pdf.loader import open_pdf
from .language import SAMPLE as LANGUAGE_SAMPLE
from .language import detect_language
from .text import PageText, build_page_text

#: Serialises every PyMuPDF call of the process (PyMuPDF is not thread-safe).
MUPDF_LOCK = threading.RLock()

_GENERATED_TITLE = re.compile(
    r"^(?:untitled|sem t[ií]tulo|microsoft word\b|document\d*$|\S+\.(?:docx?|pdf|tex|dvi|indd)$)"
    r"|^[\d\W_]*$",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\S+@\S+")
#: A word broken across lines with a hyphen ("Aufhe-" then "bung").
_HYPHEN_BREAK = re.compile(r"(?<=\w)[-­]\n(?=\w)")
_STATS_SAMPLE = 16


@dataclass(frozen=True, slots=True)
class TocEntry:
    level: int
    title: str
    page: int  # 0-based


@dataclass(frozen=True, slots=True)
class DocumentInfo:
    title: str
    authors: str | None
    page_count: int
    toc: tuple[TocEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "page_count": self.page_count,
            "toc": [{"level": e.level, "title": e.title, "page": e.page} for e in self.toc],
        }


class DocumentIndex:
    """A PDF opened for reading. Thread-safe; call :meth:`close` when done."""

    def __init__(
        self,
        data: bytes,
        *,
        name: str = "",
        stats: DocumentStats | None = None,
        cache_size: int = 48,
    ) -> None:
        self._sizes: list[tuple[float, float]] = []
        with MUPDF_LOCK:
            self._doc = open_pdf(data)
            for number in range(self._doc.page_count):
                rect = self._doc[number].rect
                self._sizes.append((float(rect.width), float(rect.height)))
        self.name = name  # fallback title (e.g. the file name)
        self._stats = stats
        self._cache: OrderedDict[int, tuple[PageLayout, PageText]] = OrderedDict()
        self._cache_size = max(4, cache_size)
        self._cache_lock = threading.Lock()
        self._layout_title: str | None = None
        self._info: DocumentInfo | None = None
        self._language: str | None = None  # "" once detected as unknown

    @classmethod
    def open(cls, path: str | Path, **options: Any) -> DocumentIndex:
        file = Path(path)
        options.setdefault("name", file.stem)
        return cls(file.read_bytes(), **options)

    # ------------------------------------------------------------------ geometry and images
    @property
    def page_count(self) -> int:
        return len(self._sizes)

    def page_sizes(self) -> list[tuple[float, float]]:
        return list(self._sizes)

    def render(self, index: int, scale: float = 1.0) -> bytes:
        """PNG image of a page at ``scale`` (1.0 = 72 dpi)."""
        self._check(index)
        with MUPDF_LOCK:
            page = self._doc[index]
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            data = bytes(pixmap.tobytes("png"))
            del pixmap, page
        return data

    def page_label(self, index: int) -> str:
        """The printed page label ("iv", "12"...) or the 1-based number."""
        self._check(index)
        with MUPDF_LOCK:
            page = self._doc[index]
            label = str(page.get_label() or "")
            del page
        return label or str(index + 1)

    # ------------------------------------------------------------------ analysis
    @property
    def stats(self) -> DocumentStats:
        if self._stats is None:
            with MUPDF_LOCK:
                sample = [extract_page(self._doc[i], i) for i in _sample(self.page_count)]
            self._stats = compute_stats(sample)
        return self._stats

    def layout(self, index: int) -> PageLayout:
        return self._analyse(index)[0]

    def page_text(self, index: int) -> PageText:
        return self._analyse(index)[1]

    def _analyse(self, index: int) -> tuple[PageLayout, PageText]:
        self._check(index)
        with self._cache_lock:
            cached = self._cache.get(index)
            if cached is not None:
                self._cache.move_to_end(index)
                return cached
        stats = self.stats
        with MUPDF_LOCK:
            layout = extract_page(self._doc[index], index)
        refine_page(layout)
        detector = MathDetector(stats)
        for block in layout.blocks:
            detector.annotate(block)
        document = DocumentLayout(pages=[layout], stats=stats)
        BlockClassifier(stats).classify(document)
        if index == 0:
            self._layout_title = document.title
        result = (layout, build_page_text(layout))
        with self._cache_lock:
            self._cache[index] = result
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return result

    # ------------------------------------------------------------------ metadata and outline
    def info(self) -> DocumentInfo:
        """Title and authors (metadata, else the first page's layout) and the outline."""
        if self._info is None:
            with MUPDF_LOCK:
                metadata = dict(self._doc.metadata or {})
                raw_toc = self._doc.get_toc(simple=True)
            toc = tuple(
                TocEntry(int(item[0]), " ".join(str(item[1]).split()), int(item[2]) - 1)
                for item in raw_toc
                if str(item[1]).strip() and int(item[2]) >= 1
            )
            title = _meaningful(metadata.get("title"))
            authors = _meaningful(metadata.get("author"))
            if title is None or authors is None:
                layout = self.layout(0)
                title = title or self._layout_title
                authors = authors or _authors(layout)
            self._info = DocumentInfo(
                title=title or self.name or "Documento sem título",
                authors=authors,
                page_count=self.page_count,
                toc=toc,
            )
        return self._info

    def language(self) -> str | None:
        """The language the document is written in (``de``, ``pt``…), from its first pages."""
        if self._language is None:
            pieces: list[str] = []
            size = 0
            for number in range(min(self.page_count, 24)):
                text = self.page_text(number).clean()
                pieces.append(text)
                size += len(text)
                if size >= LANGUAGE_SAMPLE:
                    break
            self._language = detect_language(" ".join(pieces)) or ""
        return self._language or None

    def section_at(self, page: int, offset: int = 0) -> tuple[str, ...]:
        """Section path ("Chapter 3", "3.2 Results") of a position, from the outline or,
        without one, the nearest heading before it."""
        toc = self.info().toc
        if toc:
            path: list[TocEntry] = []
            for entry in toc:
                if entry.page > page:
                    continue
                if entry.page == page and not self._heading_before(entry.title, page, offset):
                    continue
                path = [e for e in path if e.level < entry.level]
                path.append(entry)
            return tuple(entry.title for entry in path)
        for number in range(page, max(-1, page - 15), -1):
            text = self.page_text(number)
            for block_number in range(len(text.blocks) - 1, -1, -1):
                block = text.blocks[block_number]
                if number == page and block.start > offset:
                    continue
                if block.role is BlockRole.HEADING:
                    return (text.paragraph(block_number),)
        return ()

    def _heading_before(self, title: str, page: int, offset: int) -> bool:
        """Is the outline entry ``title`` on ``page`` located before ``offset``?"""
        wanted = _normalise(title)[:40]
        text = self.page_text(page)
        for number, block in enumerate(text.blocks):
            candidate = _normalise(text.paragraph(number))[:40]
            if wanted and (
                candidate.startswith(wanted)
                or (len(candidate) >= 4 and wanted.startswith(candidate))
            ):
                return block.start <= offset
        return True  # not found on the page: assume the section starts at the top

    # ------------------------------------------------------------------ search
    def search(self, query: str, *, limit: int = 300) -> list[tuple[int, list[BBox]]]:
        """Pages and boxes where ``query`` occurs (case-insensitive), at most ``limit`` hits."""
        query = query.strip()
        results: list[tuple[int, list[BBox]]] = []
        if not query:
            return results
        found = 0
        for index in range(self.page_count):
            with MUPDF_LOCK:
                page = self._doc[index]
                boxes = [BBox(r.x0, r.y0, r.x1, r.y1) for r in page.search_for(query)]
                del page
            if boxes:
                results.append((index, boxes[: limit - found]))
                found += len(boxes)
                if found >= limit:
                    break
        return results

    def occurrences(self, terms: Sequence[str]) -> dict[str, list[tuple[int, int]]]:
        """``(page, count)`` of each term in the book, case-insensitive, in one pass.

        Reads the plain text of every page once (a word hyphenated across lines counts),
        so many terms cost about as much as one.
        """
        needles = {term: " ".join(term.casefold().split()) for term in terms if term.strip()}
        found: dict[str, list[tuple[int, int]]] = {term: [] for term in needles}
        if not needles:
            return found
        for index in range(self.page_count):
            with MUPDF_LOCK:
                page = self._doc[index]
                text = page.get_text("text")
                del page
            flat = " ".join(_HYPHEN_BREAK.sub("", text).casefold().split())
            for term, needle in needles.items():
                count = flat.count(needle)
                if count:
                    found[term].append((index, count))
        return found

    def close(self) -> None:
        with MUPDF_LOCK:
            self._doc.close()

    def _check(self, index: int) -> None:
        if not 0 <= index < self.page_count:
            raise IndexError(f"Page {index} is outside 0-{self.page_count - 1}")


def _sample(page_count: int) -> list[int]:
    """The first pages plus pages spread over the rest of the document."""
    head = list(range(min(8, page_count)))
    rest = page_count - len(head)
    extra = min(_STATS_SAMPLE - len(head), rest)
    step = rest / extra if extra > 0 else 0
    return head + [len(head) + int(step * i) for i in range(max(extra, 0))]


def _meaningful(value: object) -> str | None:
    text = " ".join(str(value or "").split())
    if len(text) < 3 or _GENERATED_TITLE.match(text):
        return None
    return text


def _authors(layout: PageLayout) -> str | None:
    names = []
    for block in layout.blocks:
        if block.role is not BlockRole.AUTHOR:
            continue
        for line in block.lines:
            # "Jane Doe, jane@x.org" -> "Jane Doe"; "{kahe, v-shren}@x.com" -> dropped
            text = _EMAIL.sub(" ", re.sub(r"\{[^}]*\}\s*@\S+", " ", line.text))
            name = " ".join(text.split()).strip(" ,;")
            if name:
                names.append(name)
    return "; ".join(names)[:300] or None


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())
