import pymupdf

from polyglotpdf.model import BBox
from polyglotpdf.pdf.content_filter import ElementKind, PointIndex, filter_page_content


def origins(page: pymupdf.Page) -> list[tuple[str, float, float]]:
    raw = page.get_text("rawdict")
    return [
        (c["c"], c["origin"][0], c["origin"][1])
        for block in raw["blocks"]
        if block["type"] == 0
        for line in block["lines"]
        for span in line["spans"]
        for c in span["chars"]
    ]


def test_point_index_tolerance() -> None:
    index = PointIndex([(10.0, 20.0)], tolerance=0.25)
    assert index.contains(10.2, 19.9)
    assert not index.contains(10.4, 20.0)
    assert len(index) == 1


def test_removes_only_the_selected_glyphs() -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Hello", fontname="helv", fontsize=12)
    page.insert_text((140, 100), "World", fontname="helv", fontsize=12)
    world = [(x, y) for c, x, y in origins(page) if x >= 139 and not c.isspace()]
    stats = filter_page_content(page, remove_glyph=PointIndex(world).contains)
    assert stats.removed == 5
    assert page.get_text().split() == ["Hello"]


def test_culls_drawings_inside_an_area_only() -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_line((100, 200), (150, 200))
    page.draw_line((300, 200), (350, 200))
    area = BBox(90, 190, 160, 210)
    stats = filter_page_content(
        page,
        remove_glyph=lambda x, y: False,
        cull=lambda box, kind: kind is ElementKind.PATH and area.contains(box),
    )
    assert stats.culled == 1
    remaining = page.get_drawings()
    assert len(remaining) == 1 and remaining[0]["rect"].x0 >= 299
