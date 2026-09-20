"""Shared fixtures and builders for synthetic model objects and PDFs."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from polyglotpdf.analysis.fonts import style_from_font
from polyglotpdf.model import BBox, Block, Char, Line, Span, union_all

REPO = Path(__file__).resolve().parent.parent
PAPER = REPO / "paper_test.pdf"

# ---------------------------------------------------------------------- model builders
CHAR_WIDTH = 5.0


def make_span(
    text: str,
    font: str = "Times-Roman",
    *,
    x: float = 0.0,
    baseline: float = 100.0,
    size: float = 10.0,
    flags: int = 4,
) -> Span:
    width = CHAR_WIDTH * size / 10
    chars = [
        Char(
            c,
            x + i * width,
            baseline,
            BBox(x + i * width, baseline - 0.7 * size, x + (i + 1) * width, baseline + 0.2 * size),
        )
        for i, c in enumerate(text)
    ]
    box = BBox(x, baseline - 0.7 * size, x + len(text) * width, baseline + 0.2 * size)
    return Span(
        font=font,
        size=size,
        flags=flags,
        color=0,
        bbox=box,
        baseline=baseline,
        ascender=0.8,
        descender=-0.2,
        chars=chars,
        style=style_from_font(font, flags),
    )


def make_line(
    parts: Sequence[tuple[Any, ...]],
    *,
    x: float = 50.0,
    baseline: float = 100.0,
    size: float = 10.0,
    direction: tuple[float, float] = (1.0, 0.0),
) -> Line:
    """``parts`` are (text, font) or (text, font, overrides) tuples laid out left to right."""
    spans = []
    for part in parts:
        text, font = part[0], part[1]
        options = dict(part[2]) if len(part) > 2 else {}
        span = make_span(
            text,
            font,
            x=x,
            baseline=options.pop("baseline", baseline),
            size=options.pop("size", size),
            **options,
        )
        spans.append(span)
        x = span.bbox.x1
    box = union_all(s.bbox for s in spans)
    assert box is not None
    return Line(spans=spans, bbox=box, direction=direction)


def make_block(lines: Sequence[Line], uid: str = "p1b0", page: int = 0) -> Block:
    box = union_all(line.bbox for line in lines)
    assert box is not None
    return Block(uid=uid, page=page, bbox=box, lines=list(lines))


# ---------------------------------------------------------------------- PDF builders
def _put(
    page: pymupdf.Page, x: float, y: float, parts: Sequence[tuple[str, str]], size: float = 10
) -> None:
    for text, font in parts:
        page.insert_text((x, y), text, fontname=font, fontsize=size)
        x += pymupdf.get_text_length(text, fontname=font, fontsize=size)


def build_sample_pdf(path: Path) -> Path:
    """One page: title, author, heading, paragraphs with inline math, formula, references."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    _put(page, 72, 90, [("A Study of Things", "tibo")], size=20)
    _put(page, 72, 118, [("Jane Doe, jane@example.org", "tiro")], size=11)
    _put(page, 72, 170, [("1. Introduction", "tibo")], size=13)
    _put(
        page,
        72,
        195,
        [
            ("The parameter ", "tiro"),
            ("a", "symb"),
            (" controls the growth of the system and", "tiro"),
        ],
    )
    _put(page, 72, 207, [("the rate at which the population changes over", "tiro")])
    _put(page, 72, 219, [("time, as described by the equation below.", "tiro")])
    _put(page, 250, 262, [("a + b = g", "symb")])
    _put(page, 500, 262, [("(1)", "tiro")])
    _put(
        page,
        72,
        300,
        [
            ("Growth is fast when ", "tiro"),
            ("a", "symb"),
            (" is large, and slow otherwise.", "tiro"),
        ],
    )
    _put(page, 72, 350, [("References", "tibo")], size=12)
    _put(
        page, 72, 370, [("[1] J. Doe. Things and Stuff. Journal of Things, 2020.", "tiro")], size=9
    )
    _put(page, 72, 382, [("[2] R. Roe. More Things. Proceedings of Stuff, 2021.", "tiro")], size=9)
    doc.save(path)
    doc.close()
    return path


def build_two_column_pdf(path: Path) -> Path:
    """A paragraph that starts at the bottom of the left column and ends in the right one."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    left = [
        "Translation works better with whole paragraphs,",
        "because the model sees complete sentences and",
        "the context around them, which is why this text",
        "keeps going until the very bottom of the",
    ]
    right = [
        "column and only finishes here, at the top of the",
        "second column, where the sentence reaches its end.",
    ]
    for number, text in enumerate(left):
        _put(page, 50, 700 + 12 * number, [(text, "tiro")])
    for number, text in enumerate(right):
        _put(page, 330, 106 + 12 * number, [(text, "tiro")])
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    return build_sample_pdf(tmp_path / "sample.pdf")


@pytest.fixture
def two_column_pdf(tmp_path: Path) -> Path:
    return build_two_column_pdf(tmp_path / "columns.pdf")


@pytest.fixture
def paper_pdf() -> Path:
    if not PAPER.is_file():
        pytest.skip("paper_test.pdf not available")
    return PAPER
