from polyglotpdf.analysis.structure import split_block, split_line
from polyglotpdf.model import BlockRole, Line, union_all

from .conftest import make_block, make_line, make_span


def test_table_rows_become_cells() -> None:
    lines = [
        make_line([("layer name", "Times-Roman")], x=50, baseline=100),
        make_line([("output size", "Times-Roman")], x=200, baseline=100),
        make_line([("conv1", "Times-Roman")], x=50, baseline=112),
        make_line([("112x112", "Times-Roman")], x=200, baseline=112),
    ]
    cells = split_block(make_block(lines))
    assert [cell.text for cell in cells] == ["layer name", "output size", "conv1", "112x112"]
    assert all(cell.role is BlockRole.TABLE for cell in cells)


def test_a_line_is_split_at_wide_gaps() -> None:
    spans = [make_span("plain", x=50), make_span("ResNet", x=150)]
    box = union_all(span.bbox for span in spans)
    assert box is not None
    parts = split_line(Line(spans=spans, bbox=box))
    assert [part.text for part in parts] == ["plain", "ResNet"]
    assert parts[1].bbox.x0 == 150


def test_prose_lines_are_not_split() -> None:
    block = make_block(
        [
            make_line([("An ordinary paragraph line", "Times-Roman")], baseline=100),
            make_line([("followed by another line.", "Times-Roman")], baseline=112),
        ]
    )
    assert split_block(block) == [block]
