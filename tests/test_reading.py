"""Reading support: page text, document index and passage context (no network)."""

from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest

from polyglotpdf.reading import Anchor, DocumentIndex, PassageContext, build_context, join_lines


def offset_of(index: DocumentIndex, page: int, needle: str) -> int:
    text = index.page_text(page).text
    found = text.find(needle)
    assert found >= 0, f"{needle!r} not in page {page}: {text!r}"
    return found


@pytest.fixture
def sample_index(sample_pdf: Path) -> Iterator[DocumentIndex]:
    index = DocumentIndex.open(sample_pdf)
    yield index
    index.close()


def test_join_lines_undoes_hyphenation() -> None:
    assert join_lines(["an exam-", "ple of text"]) == "an example of text"
    assert join_lines(["state-of-the-", "art methods"]) == "state-of-the-art methods"
    assert join_lines(["The end.", "  Next   line "]) == "The end. Next line"
    assert join_lines(["a hyphen at the end-", "Capital"]) == "a hyphen at the end- Capital"
    assert join_lines(["soft­", "hyphen"]) == "softhyphen"


def test_words_cover_the_page_text_with_exact_offsets(sample_index: DocumentIndex) -> None:
    page = sample_index.page_text(0)
    assert page.words and page.text.startswith("A Study of Things")
    for word, following in zip(page.words, page.words[1:], strict=False):
        assert word.end == following.start
        assert page.text[word.start : word.end].strip()
        assert word.bbox.width > 0
    title = page.words[:4]  # "A Study of Things": one line box for every word
    assert len({(round(w.bbox.y0, 2), round(w.bbox.y1, 2)) for w in title}) == 1
    layer = page.to_layer()
    assert layer["width"] == 595 and len(layer["words"]) == len(page.words)
    assert layer["words"][0][4:] == [0, "A "]
    assert all("\n" not in word[5] for word in layer["words"])


def test_blocks_are_located_by_offset(sample_index: DocumentIndex) -> None:
    page = sample_index.page_text(0)
    gap = page.blocks[0].end + 1  # inside the blank line between the first two blocks
    assert page.locate(0) == 0
    assert page.locate(gap, forward=True) == 1
    assert page.locate(gap, forward=False) == 0
    assert page.locate(len(page.text) + 5) is None


def test_document_info_comes_from_the_first_page(sample_index: DocumentIndex) -> None:
    info = sample_index.info()
    assert info.title == "A Study of Things"
    assert info.authors is not None and "Jane Doe" in info.authors and "@" not in info.authors
    assert info.page_count == 1 and info.toc == ()
    assert info.to_dict()["toc"] == []


def test_render_label_and_search(sample_index: DocumentIndex) -> None:
    assert sample_index.render(0, 0.5).startswith(b"\x89PNG")
    assert sample_index.page_label(0) == "1"
    hits = sample_index.search("things")
    assert hits and hits[0][0] == 0 and len(hits[0][1]) >= 2
    assert sample_index.search("   ") == []
    with pytest.raises(IndexError):
        sample_index.page_text(3)


def test_section_from_headings(sample_index: DocumentIndex) -> None:
    growth = offset_of(sample_index, 0, "Growth is fast")
    assert sample_index.section_at(0, growth) == ("1. Introduction",)
    reference = offset_of(sample_index, 0, "[1] J. Doe")
    assert sample_index.section_at(0, reference) == ("References",)
    assert sample_index.section_at(0, 0) == ()


def test_section_from_the_outline(tmp_path: Path) -> None:
    path = tmp_path / "book.pdf"
    doc = pymupdf.open()
    pages = [
        ["Chapter One", "Some opening text here.", "Part A", "Text of part A."],
        ["Chapter Two", "Text of the second chapter."],
    ]
    for lines in pages:
        page = doc.new_page()
        for row, line in enumerate(lines):
            size = 16 if len(line.split()) <= 2 else 11
            page.insert_text((72, 100 + 60 * row), line, fontsize=size)
    doc.set_toc([[1, "Chapter One", 1], [2, "Part A", 1], [1, "Chapter Two", 2]])
    doc.save(path)
    doc.close()

    index = DocumentIndex.open(path)
    try:
        assert [e.title for e in index.info().toc] == ["Chapter One", "Part A", "Chapter Two"]
        opening = offset_of(index, 0, "Some opening")
        assert index.section_at(0, opening) == ("Chapter One",)
        part = offset_of(index, 0, "Text of part A")
        assert index.section_at(0, part) == ("Chapter One", "Part A")
        assert index.section_at(1, 0) == ("Chapter Two",)
    finally:
        index.close()


def test_context_joins_a_paragraph_split_across_columns(two_column_pdf: Path) -> None:
    index = DocumentIndex.open(two_column_pdf)
    try:
        start = offset_of(index, 0, "second column")
        context = build_context(index, Anchor(0, start), Anchor(0, start + len("second column")))
    finally:
        index.close()
    assert context.selection == "second column"
    assert context.current.startswith("Translation works better with whole paragraphs")
    assert context.current.endswith("where the sentence reaches its end.")
    assert "until the very bottom of the column and only finishes here" in context.current
    assert not context.whole_page and context.page == 0 and context.page_label == "1"


def test_context_around_a_selection(sample_index: DocumentIndex) -> None:
    start = offset_of(sample_index, 0, "controls the growth")
    end = Anchor(0, start + len("controls the growth"))
    context = build_context(sample_index, end, Anchor(0, start), size="short")  # any order
    assert context.selection == "controls the growth"
    assert context.current.startswith("The parameter")
    assert "1. Introduction" in context.before
    assert "Growth is fast" in context.after
    assert context.section == ("1. Introduction",)
    assert context.title == "A Study of Things"
    assert PassageContext.from_dict(context.to_dict()) == context


def test_context_of_a_whole_page(sample_index: DocumentIndex) -> None:
    context = build_context(sample_index, Anchor(0, 0))
    assert context.whole_page and context.selection == ""
    assert "Growth is fast" in context.current and "A Study of Things" in context.current
    blank = build_context(sample_index, Anchor(0, 0), Anchor(0, 0))  # empty selection
    assert blank.whole_page


def test_paper_title_and_abstract(paper_pdf: Path) -> None:
    index = DocumentIndex.open(paper_pdf)
    try:
        assert index.info().title.startswith("Deep Residual Learning")
        start = offset_of(index, 0, "Deeper neural networks are more difficult to train")
        context = build_context(index, Anchor(0, start), Anchor(0, start + 30))
    finally:
        index.close()
    assert "Deeper neural networks are more difficult to train" in context.current
    assert context.page_count == 12
