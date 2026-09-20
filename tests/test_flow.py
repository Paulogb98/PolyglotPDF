from collections.abc import Sequence

from polyglotpdf.analysis.classifier import TEXT_ROLES
from polyglotpdf.analysis.flow import translation_units
from polyglotpdf.analysis.math_detect import MathDetector
from polyglotpdf.model import Block, BlockRole, DocumentLayout, DocumentStats, PageLayout

from .conftest import make_block, make_line

STATS = DocumentStats(body_size=10.0, body_font="times", tex_body=False)


def block(
    uid: str,
    texts: Sequence[str],
    *,
    x: float = 50.0,
    y: float = 100.0,
    page: int = 0,
    size: float = 10.0,
    role: BlockRole = BlockRole.PARAGRAPH,
) -> Block:
    lines = [
        make_line([(text, "Times-Roman")], x=x, baseline=y + 12 * i, size=size)
        for i, text in enumerate(texts)
    ]
    result = make_block(lines, uid=uid, page=page)
    MathDetector(STATS).annotate(result)
    result.role = role
    return result


def units(*pages: Sequence[Block]) -> list[list[str]]:
    layout = DocumentLayout(
        pages=[
            PageLayout(index=i, width=600, height=800, blocks=list(blocks))
            for i, blocks in enumerate(pages)
        ],
        stats=STATS,
    )
    return [[b.uid for b in unit] for unit in translation_units(layout, TEXT_ROLES)]


OPEN = ["the first part of a long paragraph that", "continues in the other column with the"]


def test_paragraph_continuing_in_the_next_column_is_one_unit() -> None:
    a = block("a", OPEN, y=700)
    b = block("b", ["Rest of the sentence.", "And more text."], x=320, y=60)
    assert units([a, b]) == [["a", "b"]]


def test_lowercase_start_links_even_after_one_line() -> None:
    a = block("a", ["a single line that goes on and"])
    b = block("b", ["finishes in the next block."], x=320)
    assert units([a, b]) == [["a", "b"]]


def test_complete_paragraphs_stay_separate() -> None:
    a = block("a", ["A complete paragraph.", "It ends with a period."])
    b = block("b", ["Another paragraph starts here.", "And ends here."], y=200)
    assert units([a, b]) == [["a"], ["b"]]


def test_open_sentence_needs_more_than_one_line() -> None:
    a = block("a", ["Short line without a period"])
    b = block("b", ["Another block that starts uppercase."], y=200)
    assert units([a, b]) == [["a"], ["b"]]


def test_across_pages_with_page_furniture_in_between() -> None:
    a = block("a", OPEN, y=700)
    header = block("h", ["Journal of Things"], y=20, page=1, role=BlockRole.HEADER_FOOTER)
    number = block("n", ["2"], y=780, page=1, role=BlockRole.NON_TEXT)
    b = block("b", ["rest of the sentence on the next page."], y=60, page=1)
    assert units([a], [header, number, b]) == [["a", "b"], ["h"]]


def test_display_math_and_headings_break_the_flow() -> None:
    a = block("a", OPEN)
    eq = block("eq", ["x"], y=200, role=BlockRole.DISPLAY_MATH)
    b = block("b", ["where x is the input."], y=230)
    assert units([a, eq, b]) == [["a"], ["b"]]
    heading = block("h", ["2. Method"], y=200, role=BlockRole.HEADING)
    c = block("c", ["lowercase start after a heading."], y=230)
    assert units([block("a2", OPEN), heading, c]) == [["a2"], ["h"], ["c"]]


def test_different_text_size_breaks_the_flow() -> None:
    a = block("a", OPEN)
    b = block("b", ["smaller text that is a footnote-like block."], x=320, size=8.0)
    assert units([a, b]) == [["a"], ["b"]]
