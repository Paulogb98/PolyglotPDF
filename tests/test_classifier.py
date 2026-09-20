from typing import Any

from polyglotpdf.analysis.classifier import TEXT_ROLES, BlockClassifier, translatable_roles
from polyglotpdf.analysis.math_detect import MathDetector
from polyglotpdf.config import ContentSettings
from polyglotpdf.model import Block, BlockRole, DocumentLayout, DocumentStats, PageLayout

from .conftest import make_block, make_line

STATS = DocumentStats(body_size=10.0, body_font="times", tex_body=False)
PROSE = "This is ordinary prose with enough words to be a paragraph of text."


def paragraph(y: float, uid: str, text: str = PROSE, size: float = 10.0) -> Block:
    return make_block(
        [
            make_line([(text, "Times-Roman")], baseline=y, size=size),
            make_line([(text, "Times-Roman")], baseline=y + 12, size=size),
        ],
        uid=uid,
    )


def single(
    y: float, uid: str, text: str, font: str = "Times-Roman", size: float = 10.0, **kw: Any
) -> Block:
    return make_block([make_line([(text, font)], baseline=y, size=size, **kw)], uid=uid)


def classify(*blocks: Block, index: int = 0) -> DocumentLayout:
    page = PageLayout(index=index, width=600, height=800, blocks=list(blocks))
    detector = MathDetector(STATS)
    for block in blocks:
        detector.annotate(block)
    layout = DocumentLayout(pages=[page], stats=STATS)
    BlockClassifier(STATS).classify(layout)
    return layout


def test_basic_roles() -> None:
    blocks = [
        single(200, "h", "2. Related Work", font="Times-Bold", size=12),
        paragraph(230, "p"),
        single(300, "cap", "Figure 3. Results on the validation set."),
        single(330, "eq", "x + y = z", font="CMMI10"),
        single(360, "num", "12"),
        single(400, "rot", "arXiv stamp text", direction=(0.0, -1.0)),
        single(430, "li", "• first item of a list with some words"),
    ]
    classify(*blocks, index=3)
    assert {b.uid: b.role for b in blocks} == {
        "h": BlockRole.HEADING,
        "p": BlockRole.PARAGRAPH,
        "cap": BlockRole.CAPTION,
        "eq": BlockRole.DISPLAY_MATH,
        "num": BlockRole.NON_TEXT,
        "rot": BlockRole.ROTATED,
        "li": BlockRole.LIST_ITEM,
    }


def test_title_and_authors_on_first_page() -> None:
    title = single(90, "t", "A Study of Things", font="Times-Bold", size=20)
    author = single(120, "a", "Jane Doe, jane@example.org", size=11)
    abstract = single(160, "abs", "Abstract", font="Times-Bold", size=12)
    body = paragraph(190, "p")
    layout = classify(title, author, abstract, body)
    assert title.role is BlockRole.TITLE
    assert author.role is BlockRole.AUTHOR
    assert abstract.role is BlockRole.HEADING
    assert body.role is BlockRole.PARAGRAPH
    assert layout.title == "A Study of Things"


def test_references_section_until_the_next_heading() -> None:
    heading = single(100, "r", "References", font="Times-Bold", size=12)
    entry = paragraph(130, "e", "[1] J. Doe. Things and Stuff. Journal of Things, 2020.", size=9)
    appendix = single(200, "ap", "A. Additional Experiments", font="Times-Bold", size=12)
    after = paragraph(230, "p")
    classify(heading, entry, appendix, after, index=5)
    assert heading.role is BlockRole.HEADING
    assert entry.role is BlockRole.REFERENCE
    assert appendix.role is BlockRole.HEADING
    assert after.role is BlockRole.PARAGRAPH


def test_page_margins_are_headers_and_footers() -> None:
    header = single(40, "hd", "Journal of Things, Vol. 3")
    classify(header, index=2)
    assert header.role is BlockRole.HEADER_FOOTER


def test_table_cells_with_text_are_kept_as_cells() -> None:
    cell = single(300, "c1", "layer name")
    numbers = single(300, "c2", "27.94")
    cell.role = numbers.role = BlockRole.TABLE  # as produced by table splitting
    classify(cell, numbers)
    assert cell.role is BlockRole.TABLE
    assert numbers.role is BlockRole.NON_TEXT


def test_every_kind_of_text_is_translated() -> None:
    roles = translatable_roles(ContentSettings())
    assert roles == set(TEXT_ROLES)
    assert {BlockRole.TITLE, BlockRole.REFERENCE, BlockRole.AUTHOR, BlockRole.TABLE} <= roles
    assert BlockRole.DISPLAY_MATH not in roles and BlockRole.CODE not in roles
    assert BlockRole.CODE in translatable_roles(ContentSettings(translate_code=True))
