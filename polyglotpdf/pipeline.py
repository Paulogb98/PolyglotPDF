"""End-to-end orchestration: analyse -> segment -> translate -> render -> save."""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

from .analysis.classifier import BlockClassifier, translatable_roles
from .analysis.document import compute_stats
from .analysis.flow import translation_units
from .analysis.math_detect import MathDetector
from .analysis.structure import refine_page
from .config import Settings, default_cache_path
from .errors import Cancelled, InputError
from .model import DocumentLayout, PageLayout
from .pdf.extractor import extract_page
from .pdf.loader import load_pdf_bytes, open_pdf, parse_page_range
from .pdf.snippets import SnippetFactory
from .progress import NullProgress, ProgressReporter
from .render.bilingual import side_by_side
from .render.debug import annotate_layout
from .render.fonts import FontProvider
from .render.hyphenation import create_hyphenator
from .render.renderer import DocumentRenderer
from .render.typesetter import Typesetter
from .segmentation.markup import visible_text
from .segmentation.segmenter import Segment, Segmenter, SegmentStatus
from .translation.base import TranslationContext, Translator
from .translation.cache import TranslationCache
from .translation.glossary import Glossary
from .translation.languages import base as language_base
from .translation.registry import create_translator
from .translation.service import TranslationService

log = logging.getLogger(__name__)


@dataclass(slots=True)
class TranslationReport:
    input_path: str
    output_path: str | None = None
    bilingual_path: str | None = None
    engine: str = ""
    target_lang: str = ""
    pages: int = 0
    blocks: int = 0
    roles: dict[str, int] = field(default_factory=dict)
    segments: int = 0
    merged_paragraphs: int = 0  # paragraphs rejoined across columns or pages
    translated: int = 0
    failed: int = 0
    cache_hits: int = 0
    requests: int = 0
    shrunk: int = 0
    overflowed: int = 0
    min_scale: float = 1.0
    scanned_pages: list[int] = field(default_factory=list)
    missing_glyphs: str = ""
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Estimate:
    """What a translation would involve, computed without translating."""

    pages: int
    blocks: int
    segments: int
    merged_paragraphs: int
    characters: int  # text sent for translation (formulas and markup excluded)
    words: int
    formulas: int  # inline formulas and scripts kept as vector snippets
    roles: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_output_path(input_path: Path, target_lang: str) -> Path:
    return input_path.with_name(f"{input_path.stem}.{target_lang}.pdf")


class PdfTranslator:
    """Translates PDF documents while preserving their layout and formulas."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        translator: Translator | None = None,
        progress: ProgressReporter | None = None,
    ) -> None:
        self.settings = (settings or Settings()).validate()
        self._translator = translator
        self.progress = progress or NullProgress()

    # ------------------------------------------------------------------ analysis
    def analyze(
        self,
        document: pymupdf.Document,
        pages: Sequence[int],
        cancel: threading.Event | None = None,
    ) -> DocumentLayout:
        self.progress.start("analyze", len(pages))
        layouts: list[PageLayout] = []
        for index in pages:
            _check(cancel)
            layouts.append(extract_page(document[index], index))
            self.progress.advance("analyze")
        self.progress.finish("analyze")

        stats = compute_stats(layouts)
        source_lang = language_base(self.settings.translation.source_lang)
        detector = MathDetector(stats, greek_is_math=source_lang != "el")
        for page in layouts:
            refine_page(page)
            for block in page.blocks:
                detector.annotate(block)
        layout = DocumentLayout(pages=layouts, stats=stats)
        BlockClassifier(stats).classify(layout)
        return layout

    def segments(self, layout: DocumentLayout) -> tuple[list[Segment], list[int]]:
        """Translation segments of an analysed document, and the (1-based) scanned pages."""
        roles = translatable_roles(self.settings.content)
        segmenter = Segmenter()
        segments = [
            segment
            for unit in translation_units(layout, roles)
            if (segment := segmenter.build(unit)) is not None
        ]
        scanned = [page.index + 1 for page in layout.pages if page.scanned]
        return segments, scanned

    # ------------------------------------------------------------------ translation
    def translate(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        *,
        cancel: threading.Event | None = None,
    ) -> TranslationReport:
        """Translate ``input_path``; set ``cancel`` from another thread to stop early."""
        started = time.perf_counter()
        settings = self.settings
        source_path = Path(input_path)
        output = (
            Path(output_path)
            if output_path
            else default_output_path(source_path, settings.translation.target_lang)
        )
        if output.resolve() == source_path.resolve():
            raise InputError("The output file would overwrite the input")
        report = TranslationReport(
            input_path=str(source_path), target_lang=settings.translation.target_lang
        )

        data = load_pdf_bytes(source_path)
        source = open_pdf(data)  # untouched: source of the formula snippets
        target = open_pdf(data)  # modified in place
        snippets = SnippetFactory(source)
        translator: Translator | None = None
        try:
            # Built before the (long) analysis, so a missing key or model fails at once.
            translator = self._translator or create_translator(settings.translation)
            report.engine = translator.fingerprint()
            glossary = (
                Glossary.load(settings.translation.glossary_path)
                if settings.translation.glossary_path
                else Glossary()
            )
            if not glossary.is_empty and not translator.supports_glossary:
                report.warnings.append(
                    f"The glossary is not applied by the {translator.name} engine"
                )

            pages = parse_page_range(settings.pages, source.page_count)
            layout = self.analyze(source, pages, cancel)
            report.pages = len(pages)
            report.blocks = sum(len(page.blocks) for page in layout.pages)
            report.roles = dict(Counter(block.role.value for block in layout.blocks()))

            segments, report.scanned_pages = self.segments(layout)
            report.segments = len(segments)
            report.merged_paragraphs = sum(1 for segment in segments if segment.merged)
            for number in report.scanned_pages:
                report.warnings.append(f"Page {number} is a scan with an OCR layer; left as is")
            _check(cancel)

            self._translate(segments, layout, translator, glossary, report, cancel)
            _check(cancel)

            self._render(target, snippets, layout, segments, report, cancel)

            if settings.output.bilingual:
                dual_path = output.with_name(f"{output.stem}.dual{output.suffix}")
                dual = side_by_side(source, target, pages)
                try:
                    self._save(dual, dual_path)
                finally:
                    dual.close()
                report.bilingual_path = str(dual_path)
            if len(pages) != target.page_count and not settings.output.keep_all_pages:
                target.select(list(pages))
            self._save(target, output)
            report.output_path = str(output)
        finally:
            snippets.close()
            source.close()
            target.close()
        for warning in report.warnings:
            log.warning(warning)
        report.elapsed_seconds = round(time.perf_counter() - started, 2)
        return report

    def estimate(self, input_path: str | Path) -> Estimate:
        """Count what would be translated (pages, segments, characters) without translating."""
        document = open_pdf(load_pdf_bytes(Path(input_path)))
        try:
            pages = parse_page_range(self.settings.pages, document.page_count)
            layout = self.analyze(document, pages)
        finally:
            document.close()
        segments, _ = self.segments(layout)
        texts = [visible_text(segment.source) for segment in segments]
        return Estimate(
            pages=len(pages),
            blocks=sum(len(page.blocks) for page in layout.pages),
            segments=len(segments),
            merged_paragraphs=sum(1 for segment in segments if segment.merged),
            characters=sum(len(text) for text in texts),
            words=sum(len(text.split()) for text in texts),
            formulas=sum(len(segment.placeholders) for segment in segments),
            roles=dict(Counter(block.role.value for block in layout.blocks())),
        )

    def inspect(
        self, input_path: str | Path, output_path: str | Path | None = None
    ) -> tuple[DocumentLayout, Path]:
        """Analyse a document and write a copy annotated with the detected block roles."""
        source_path = Path(input_path)
        output = (
            Path(output_path)
            if output_path
            else source_path.with_name(f"{source_path.stem}.inspect.pdf")
        )
        document = open_pdf(load_pdf_bytes(source_path))
        try:
            pages = parse_page_range(self.settings.pages, document.page_count)
            layout = self.analyze(document, pages)
            annotate_layout(document, layout, translatable_roles(self.settings.content))
            if len(pages) != document.page_count:
                document.select(list(pages))
            output.parent.mkdir(parents=True, exist_ok=True)
            document.save(str(output), garbage=3, deflate=True)
        finally:
            document.close()
        return layout, output

    # ------------------------------------------------------------------ steps
    def _translate(
        self,
        segments: list[Segment],
        layout: DocumentLayout,
        translator: Translator,
        glossary: Glossary,
        report: TranslationReport,
        cancel: threading.Event | None,
    ) -> None:
        ts = self.settings.translation
        context = TranslationContext(
            ts.source_lang, ts.target_lang, glossary, document_title=layout.title
        )
        cache = TranslationCache(ts.cache_path or default_cache_path()) if ts.use_cache else None
        try:
            service = TranslationService(
                translator,
                context,
                cache=cache,
                concurrency=ts.concurrency,
                progress=self.progress,
                cancel=cancel,
            )
            stats = service.run(segments)
        finally:
            if cache is not None:
                cache.close()
        report.cache_hits = stats.cache_hits
        report.requests = stats.requests

    def _render(
        self,
        target: pymupdf.Document,
        snippets: SnippetFactory,
        layout: DocumentLayout,
        segments: list[Segment],
        report: TranslationReport,
        cancel: threading.Event | None,
    ) -> None:
        settings = self.settings
        target_lang = settings.translation.target_lang
        fonts = FontProvider(settings.fonts, target_lang)
        hyphenator = create_hyphenator(target_lang) if settings.layout.hyphenate else None
        renderer = DocumentRenderer(
            target, snippets, fonts, Typesetter(fonts, hyphenator), settings.layout
        )
        self.progress.start("render", len(layout.pages))
        stats = renderer.render(
            layout.pages,
            segments,
            on_page=lambda: self.progress.advance("render"),
            cancel=cancel,
        )
        self.progress.finish("render")

        report.translated = stats.translated
        report.shrunk = stats.shrunk
        report.overflowed = stats.overflowed
        report.min_scale = stats.min_scale
        failed = [s for s in segments if s.status is not SegmentStatus.TRANSLATED]
        report.failed = len(failed)
        report.failures = [f"{s.uid}: {s.note or s.status.value}" for s in failed[:50]]
        report.missing_glyphs = "".join(sorted(fonts.missing))
        if fonts.missing:
            report.warnings.append(f"No font covers these characters: {report.missing_glyphs}")

    def _save(self, document: pymupdf.Document, path: Path) -> None:
        if self.settings.output.subset_fonts:
            try:
                document.subset_fonts()
            except Exception as exc:  # subsetting is an optimisation only
                log.warning("Font subsetting failed (%s); embedding full fonts", exc)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            document.save(str(path), garbage=4, deflate=True)
        except (OSError, RuntimeError) as exc:
            raise InputError(f"Cannot write {path}: {exc}") from exc


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled("Translation cancelled")


def translate_pdf(
    input_path: str | Path,
    output_path: str | Path | None = None,
    settings: Settings | None = None,
    *,
    translator: Translator | None = None,
    progress: ProgressReporter | None = None,
    cancel: threading.Event | None = None,
) -> TranslationReport:
    """Convenience wrapper around :class:`PdfTranslator`."""
    return PdfTranslator(settings, translator=translator, progress=progress).translate(
        input_path, output_path, cancel=cancel
    )
