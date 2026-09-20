from collections.abc import Sequence

import pytest

from polyglotpdf.model import TextStyle
from polyglotpdf.render.typesetter import Align, BoxPiece, Frame, TextPiece, Typesetter, Word


class MonoMeasurer:
    """Every character is half an em wide."""

    def width(self, text: str, style: TextStyle, size: float) -> float:
        return 0.5 * size * len(text)


class FakeHyphenator:
    def __init__(self, points: dict[str, Sequence[int]]) -> None:
        self.points = points

    def split_points(self, word: str) -> Sequence[int]:
        return self.points.get(word, [])


def words(text: str) -> list[Word]:
    return [Word([TextPiece(w, TextStyle())]) for w in text.split()]


def frame(**overrides: object) -> Frame:
    values: dict[str, object] = {
        "x0": 0.0,
        "top": 0.0,
        "width": 50.0,
        "height": 100.0,
        "base_size": 10.0,
        "first_baseline": 8.0,
        "line_pitch": 12.0,
    }
    values.update(overrides)
    return Frame(**values)  # type: ignore[arg-type]


def texts(layout) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        " ".join(p.piece.text for p in line.pieces if isinstance(p.piece, TextPiece))
        for line in layout.lines
    ]


def test_breaks_lines_at_original_size() -> None:
    layout = Typesetter(MonoMeasurer()).layout(words("aaaa bbbb cccc"), frame())
    assert layout.fits and layout.scale == 1.0
    assert texts(layout) == ["aaaa bbbb", "cccc"]
    assert [line.baseline for line in layout.lines] == [8.0, 20.0]


def test_justified_lines_reach_the_right_edge_except_the_last() -> None:
    layout = Typesetter(MonoMeasurer()).layout(words("aa bb cc dd ee"), frame(align=Align.JUSTIFY))
    first, last = layout.lines
    end = first.pieces[-1].x + first.pieces[-1].width
    assert end == pytest.approx(50.0)
    assert last.pieces[-1].x + last.pieces[-1].width < 50.0


def test_center_and_right_alignment() -> None:
    centered = Typesetter(MonoMeasurer()).layout(words("ab"), frame(align=Align.CENTER))
    assert centered.lines[0].pieces[0].x == pytest.approx(20.0)
    right = Typesetter(MonoMeasurer()).layout(words("ab"), frame(align=Align.RIGHT))
    assert right.lines[0].pieces[0].x == pytest.approx(40.0)


def test_shrinks_text_to_fit_the_height() -> None:
    layout = Typesetter(MonoMeasurer()).layout(
        words("aaaa bbbb cccc dddd"), frame(height=15.0), min_scale=0.72, hard_min_scale=0.5
    )
    assert layout.fits
    assert 0.6 < layout.scale < 0.72
    assert layout.height <= 15.0 + 0.01


def test_reports_overflow_when_nothing_fits() -> None:
    layout = Typesetter(MonoMeasurer()).layout(words("aaaa bbbb"), frame(height=1.0))
    assert not layout.fits
    assert layout.scale == 0.5


def test_tall_inline_box_pushes_the_line_down() -> None:
    content = [Word([TextPiece("aaaa", TextStyle())]), Word([BoxPiece(1, 20.0, 15.0, 5.0)])]
    layout = Typesetter(MonoMeasurer()).layout(content, frame(width=30.0))
    assert len(layout.lines) == 2
    # previous text descent 2.5 + box ascent 15 + 1 (0.1 * size) > pitch 12
    assert layout.lines[1].baseline == pytest.approx(8.0 + 18.5)


def test_hyphenates_to_fill_the_line() -> None:
    hyphenator = FakeHyphenator({"extraordinary": [5]})
    layout = Typesetter(MonoMeasurer(), hyphenator).layout(
        words("aa extraordinary"), frame(width=45.0)
    )
    assert texts(layout) == ["aa extra-", "ordinary"]


def test_breaks_after_an_existing_hyphen() -> None:
    layout = Typesetter(MonoMeasurer()).layout(words("aa bem-vindo"), frame(width=40.0))
    assert texts(layout) == ["aa bem-", "vindo"]


def test_force_splits_words_longer_than_the_line() -> None:
    layout = Typesetter(MonoMeasurer()).layout(words("abcdefghijkl"), frame(width=30.0))
    assert layout.fits
    assert texts(layout) == ["abcdef", "ghijkl"]


def test_first_line_indent() -> None:
    layout = Typesetter(MonoMeasurer()).layout(words("aa bb"), frame(first_indent=10.0))
    assert layout.lines[0].pieces[0].x == pytest.approx(10.0)


def test_max_scale_caps_the_size_even_when_there_is_room() -> None:
    layout = Typesetter(MonoMeasurer()).layout(words("aa bb"), frame(), max_scale=0.8)
    assert layout.fits and layout.scale == pytest.approx(0.8)
    assert layout.size == pytest.approx(8.0)


def test_text_flows_into_the_next_frame() -> None:
    first = frame(height=15.0, align=Align.JUSTIFY)  # room for a single line
    second = frame(x0=100.0, top=200.0, align=Align.JUSTIFY)
    layout = Typesetter(MonoMeasurer()).layout(words("aaaa bbbb cccc dddd eeee"), [first, second])
    assert layout.fits and layout.scale == 1.0
    assert [line.frame for line in layout.lines] == [0, 1, 1]
    assert [line.baseline for line in layout.lines] == [8.0, 208.0, 220.0]
    assert layout.lines[1].pieces[0].x == pytest.approx(100.0)
    # The last line of the first frame is not the end of the paragraph: it is justified.
    end = layout.lines[0].pieces[-1]
    assert end.x + end.width == pytest.approx(50.0)


def test_text_shrinks_when_all_frames_are_full() -> None:
    frames = [frame(height=15.0), frame(top=200.0, height=15.0)]
    layout = Typesetter(MonoMeasurer()).layout(words("aaaa bbbb cccc dddd eeee ffff"), frames)
    assert layout.fits and layout.scale < 1.0
    assert {line.frame for line in layout.lines} == {0, 1}
