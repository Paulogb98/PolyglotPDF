"""End-to-end tests with offline engines."""

import threading
from pathlib import Path

import pymupdf
import pytest

from polyglotpdf import (
    Cancelled,
    FunctionProgress,
    PdfTranslator,
    Settings,
    page_count,
    render_page,
)
from polyglotpdf.errors import ConfigError, InputError
from polyglotpdf.model import BlockRole
from polyglotpdf.translation.dummy import EchoTranslator, PseudoTranslator

ACCENTED = set("àéîöûñšýž")


def settings(**root: object) -> Settings:
    config = Settings()
    config.translation.use_cache = False
    for key, value in root.items():
        setattr(config, key, value)
    return config


def text_of(path: Path, page: int = 0) -> str:
    with pymupdf.open(path) as doc:
        return str(doc[page].get_text())


def test_inspect_detects_the_structure(sample_pdf: Path, tmp_path: Path) -> None:
    layout, annotated = PdfTranslator(settings()).inspect(sample_pdf, tmp_path / "inspect.pdf")
    roles = {block.role for block in layout.blocks()}
    assert {
        BlockRole.TITLE,
        BlockRole.AUTHOR,
        BlockRole.HEADING,
        BlockRole.PARAGRAPH,
        BlockRole.DISPLAY_MATH,
        BlockRole.REFERENCE,
    } <= roles
    assert layout.title == "A Study of Things"
    assert annotated.is_file()


def test_all_text_is_translated_and_formulas_are_kept(sample_pdf: Path, tmp_path: Path) -> None:
    output = tmp_path / "out.pdf"
    report = PdfTranslator(settings(), translator=PseudoTranslator()).translate(sample_pdf, output)
    assert report.failed == 0 and report.translated >= 6
    text = text_of(output)
    assert "pàràmétér" in text and "parameter" not in text  # paragraph
    assert "Thîñg" in text and "A Study of Things" not in text  # title
    assert "Things and Stuff" not in text  # references are translated too
    # Symbol-font glyphs (extracted as "a", "b", "g"): the display formula plus the two
    # inline formulas, which are re-drawn from single-formula vector snippets.
    with pymupdf.open(output) as doc:
        fonts = [
            span["font"]
            for block in doc[0].get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
        ]
    assert fonts.count("Symbol") == 3


def test_display_formula_pixels_are_untouched(sample_pdf: Path, tmp_path: Path) -> None:
    output = tmp_path / "out.pdf"
    PdfTranslator(settings(), translator=PseudoTranslator()).translate(sample_pdf, output)
    with pymupdf.open(sample_pdf) as before, pymupdf.open(output) as after:
        area = before[0].search_for("a + b = g")[0] + (-1, -1, 1, 1)
        original = before[0].get_pixmap(dpi=144, clip=area).samples
        translated = after[0].get_pixmap(dpi=144, clip=area).samples
    assert original == translated


def test_echo_round_trip_preserves_the_words(sample_pdf: Path, tmp_path: Path) -> None:
    output = tmp_path / "echo.pdf"
    PdfTranslator(settings(), translator=EchoTranslator()).translate(sample_pdf, output)
    # Re-typeset blocks are appended to the content stream, so compare the words, not their order.
    assert sorted(text_of(sample_pdf).split()) == sorted(text_of(output).split())


def test_paragraph_split_across_columns_is_one_unit(two_column_pdf: Path, tmp_path: Path) -> None:
    estimate = PdfTranslator(settings()).estimate(two_column_pdf)
    assert estimate.segments == 1 and estimate.merged_paragraphs == 1

    # The chain is re-broken with other font metrics; without hyphenation the words match.
    config = settings()
    config.layout.hyphenate = False
    echo = tmp_path / "echo.pdf"
    PdfTranslator(config, translator=EchoTranslator()).translate(two_column_pdf, echo)
    assert sorted(text_of(two_column_pdf).split()) == sorted(text_of(echo).split())

    output = tmp_path / "pseudo.pdf"
    report = PdfTranslator(settings(), translator=PseudoTranslator()).translate(
        two_column_pdf, output
    )
    assert report.merged_paragraphs == 1 and report.failed == 0 and report.overflowed == 0
    with pymupdf.open(output) as doc:
        words = doc[0].get_text("words")
    left = [w[4] for w in words if w[0] < 300]
    right = [w[4] for w in words if w[0] > 320]
    assert left and right  # the translation flows through both columns
    assert any(ACCENTED & set(word) for word in right)


def test_bilingual_output(sample_pdf: Path, tmp_path: Path) -> None:
    config = settings()
    config.output.bilingual = True
    report = PdfTranslator(config, translator=PseudoTranslator()).translate(
        sample_pdf, tmp_path / "out.pdf"
    )
    assert report.bilingual_path is not None
    with pymupdf.open(report.bilingual_path) as dual:
        assert dual[0].rect.width == pytest.approx(2 * 595)


def test_estimate_counts_without_translating(sample_pdf: Path) -> None:
    estimate = PdfTranslator(settings()).estimate(sample_pdf)
    assert estimate.pages == 1 and estimate.segments >= 6
    assert estimate.formulas == 2 and estimate.characters > 100 and estimate.words > 20


def test_progress_callbacks_and_cancellation(sample_pdf: Path, tmp_path: Path) -> None:
    events: list[tuple[str, int, int]] = []
    progress = FunctionProgress(lambda stage, done, total: events.append((stage, done, total)))
    PdfTranslator(settings(), translator=EchoTranslator(), progress=progress).translate(
        sample_pdf, tmp_path / "out.pdf"
    )
    assert {stage for stage, _, _ in events} == {"analyze", "translate", "render"}
    assert all(done == total for stage, done, total in events[-1:])

    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        PdfTranslator(settings(), translator=EchoTranslator()).translate(
            sample_pdf, tmp_path / "cancelled.pdf", cancel=cancel
        )


def test_preview_helpers(sample_pdf: Path) -> None:
    assert page_count(sample_pdf) == 1
    assert render_page(sample_pdf, 0, dpi=40).startswith(b"\x89PNG")
    with pytest.raises(InputError):
        render_page(sample_pdf, 3)


def test_output_never_overwrites_the_input(sample_pdf: Path) -> None:
    with pytest.raises(InputError):
        PdfTranslator(settings(), translator=EchoTranslator()).translate(sample_pdf, sample_pdf)


def test_real_paper_first_pages(paper_pdf: Path, tmp_path: Path) -> None:
    output = tmp_path / "paper.pdf"
    report = PdfTranslator(settings(pages="1-3"), translator=PseudoTranslator()).translate(
        paper_pdf, output
    )
    assert report.pages == 3 and report.failed == 0 and report.translated > 20
    assert report.merged_paragraphs >= 1  # paragraphs continuing in the next column/page
    with pymupdf.open(output) as doc:
        assert doc.page_count == 3
        assert "arXiv:1512.03385v1" in doc[0].get_text()  # rotated stamp untouched
        page3 = doc[2].get_text()
    assert "(1)" in page3 and "(2)" in page3  # display equations untouched


def test_missing_api_key_fails_before_the_analysis(
    sample_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    stages: list[str] = []
    progress = FunctionProgress(lambda stage, done, total: stages.append(stage))
    config = settings()
    config.translation.engine = "openai"
    with pytest.raises(ConfigError):
        PdfTranslator(config, progress=progress).translate(sample_pdf, tmp_path / "out.pdf")
    assert stages == [] and not (tmp_path / "out.pdf").exists()
