from polyglotpdf.analysis.math_detect import MathDetector
from polyglotpdf.model import Block, DocumentStats, Line
from polyglotpdf.segmentation import Segment, Segmenter

from .conftest import make_block, make_line

STATS = DocumentStats(body_size=10.0, body_font="times", tex_body=False)


def annotated(*lines: Line, uid: str = "p1b0", page: int = 0) -> Block:
    block = make_block(list(lines), uid=uid, page=page)
    MathDetector(STATS).annotate(block)
    return block


def segment_of(*lines: Line) -> Segment | None:
    return Segmenter().build(annotated(*lines))


def test_formulas_become_placeholders_and_styles_become_tags() -> None:
    segment = segment_of(
        make_line(
            [
                ("The value of ", "Times-Roman"),
                ("H", "CMSY10"),
                ("(x)", "CMR10"),
                (" is com-", "Times-Roman"),
            ],
            baseline=100,
        ),
        make_line(
            [
                ("puted in ", "Times-Roman"),
                ("closed form", "Times-Italic", {"flags": 6}),
                (". See https://example.org/x.", "Times-Roman"),
            ],
            baseline=112,
        ),
    )
    assert segment is not None
    # Everything but the formula goes to the translator, URLs included.
    assert segment.source == (
        "The value of {v1} is computed in <i>closed form</i>. See https://example.org/x."
    )
    formula = segment.placeholders[1]
    assert formula.text == "H(x)" and formula.page == 0 and formula.baseline == 100


def test_monospaced_words_are_tagged_not_protected() -> None:
    segment = segment_of(
        make_line(
            [
                ("Call ", "Times-Roman"),
                ("np.zeros", "Courier", {"flags": 8}),
                (" twice", "Times-Roman"),
            ]
        )
    )
    assert segment is not None
    assert segment.source == "Call <c>np.zeros</c> twice"
    assert segment.placeholders == {}


def test_compound_hyphen_is_kept_across_lines() -> None:
    segment = segment_of(
        make_line([("a state-of-the-", "Times-Roman")], baseline=100),
        make_line([("art method", "Times-Roman")], baseline=112),
    )
    assert segment is not None and segment.source == "a state-of-the-art method"


def test_ligatures_are_expanded() -> None:
    segment = segment_of(make_line([("the ﬁrst ﬂow", "Times-Roman")]))
    assert segment is not None and segment.source == "the first flow"


def test_block_that_is_only_math_has_nothing_to_translate() -> None:
    assert segment_of(make_line([("x + y", "CMMI10")])) is None


def test_bold_block_has_no_redundant_tags() -> None:
    segment = segment_of(make_line([("Plain Network", "Times-Bold", {"flags": 20})]))
    assert segment is not None and segment.source == "Plain Network"


def test_blocks_of_one_paragraph_become_one_segment() -> None:
    first = annotated(make_line([("a paragraph that con-", "Times-Roman")], baseline=700), uid="a")
    second = annotated(
        make_line([("tinues in the next column", "Times-Roman")], x=320, baseline=100), uid="b"
    )
    segment = Segmenter().build([first, second])
    assert segment is not None
    assert segment.source == "a paragraph that continues in the next column"
    assert segment.uid == "a" and segment.merged
    assert [block.uid for block in segment.blocks] == ["a", "b"]


def test_placeholders_are_numbered_across_blocks_and_pages() -> None:
    first = annotated(make_line([("with ", "Times-Roman"), ("x", "CMMI10")]), uid="a", page=0)
    second = annotated(
        make_line([("and ", "Times-Roman"), ("y", "CMMI10"), (" too", "Times-Roman")]),
        uid="b",
        page=1,
    )
    segment = Segmenter().build([first, second])
    assert segment is not None
    assert segment.source == "with {v1} and {v2} too"
    assert [segment.placeholders[k].page for k in (1, 2)] == [0, 1]
