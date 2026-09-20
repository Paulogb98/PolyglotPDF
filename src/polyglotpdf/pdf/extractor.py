"""PyMuPDF page -> :class:`~polyglotpdf.model.PageLayout`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pymupdf

from ..analysis.fonts import normalize_font_name, style_from_font
from ..model import BBox, Block, Char, Line, PageLayout, Span, union_all

TEXT_FLAGS = (
    pymupdf.TEXT_PRESERVE_WHITESPACE
    | pymupdf.TEXT_PRESERVE_LIGATURES
    | pymupdf.TEXT_ACCURATE_BBOXES
    | pymupdf.TEXT_MEDIABOX_CLIP
)
_DRAWN = frozenset({"fill-path", "stroke-path", "fill-shade", "fill-image", "fill-imgmask"})
_IMAGES = frozenset({"fill-image", "fill-imgmask"})
_CLUSTER_GAP = 3.0
_MAX_CLUSTER_ELEMENTS = 2500
_FIGURE_MIN_OPS = 8


def extract_page(page: pymupdf.Page, index: int) -> PageLayout:
    raw = page.get_text("rawdict", flags=TEXT_FLAGS)
    blocks: list[Block] = []
    for number, block in enumerate(raw.get("blocks", [])):
        if block.get("type") != 0:
            continue
        lines: list[Line] = []
        for line in block.get("lines", []):
            spans = [span for span in map(_span, line.get("spans", [])) if span is not None]
            if spans:
                direction = line.get("dir", (1.0, 0.0))
                lines.append(
                    Line(
                        spans=spans,
                        bbox=BBox.of(line["bbox"]),
                        direction=(float(direction[0]), float(direction[1])),
                        wmode=int(line.get("wmode", 0)),
                    )
                )
        if lines:
            uid = f"p{index + 1}b{number}"
            blocks.append(Block(uid=uid, page=index, bbox=BBox.of(block["bbox"]), lines=lines))
    obstacles, graphics, scanned = _graphics(page)
    return PageLayout(
        index=index,
        width=float(page.rect.width),
        height=float(page.rect.height),
        blocks=blocks,
        graphics=graphics,
        obstacles=obstacles,
        scanned=scanned,
    )


def _span(raw: dict[str, Any]) -> Span | None:
    chars = [
        Char(c["c"], float(c["origin"][0]), float(c["origin"][1]), BBox.of(c["bbox"]))
        for c in raw.get("chars", [])
    ]
    if not chars:
        return None
    font = normalize_font_name(raw.get("font", ""))
    flags = int(raw.get("flags", 0))
    return Span(
        font=font,
        size=float(raw["size"]),
        flags=flags,
        color=int(raw.get("color", 0)),
        bbox=BBox.of(raw["bbox"]),
        baseline=float(raw["origin"][1]),
        ascender=float(raw.get("ascender", 0.8)),
        descender=float(raw.get("descender", -0.2)),
        chars=chars,
        style=style_from_font(font, flags),
    )


@dataclass(slots=True)
class _Cluster:
    box: BBox
    ops: int
    image: bool

    def absorb(self, other: _Cluster) -> None:
        self.box = self.box.union(other.box)
        self.ops += other.ops
        self.image = self.image or other.image


def _graphics(page: pymupdf.Page) -> tuple[list[BBox], list[BBox], bool]:
    """Return (obstacles, figure regions, looks-scanned) from the page's drawing log."""
    page_area = float(page.rect.width * page.rect.height)
    elements: list[tuple[BBox, bool]] = []
    visible_text = invisible_text = 0
    full_page_image = False
    for kind, rect in page.get_bboxlog():
        if kind in ("fill-text", "stroke-text"):
            visible_text += 1
            continue
        if kind == "ignore-text":  # render mode 3, e.g. the OCR layer of a scan
            invisible_text += 1
            continue
        if kind not in _DRAWN:
            continue
        box = BBox.of(rect)
        if box.area > 0.6 * page_area:  # page background or full-page scan
            full_page_image = full_page_image or kind in _IMAGES
            continue
        elements.append((box.expand(0.5), kind in _IMAGES))
    scanned = full_page_image and invisible_text > visible_text
    obstacles = [box for box, _ in elements]
    return obstacles, _figure_regions(elements), scanned


def _figure_regions(elements: list[tuple[BBox, bool]]) -> list[BBox]:
    """Group nearby drawing operations; groups with images or many operations are figures."""
    if not elements:
        return []
    if len(elements) > _MAX_CLUSTER_ELEMENTS:
        union = union_all(box for box, _ in elements)
        return [union] if union is not None else []
    clusters: list[_Cluster] = []
    for box, is_image in sorted(elements, key=lambda e: (e[0].y0, e[0].x0)):
        merged = _Cluster(box, 1, is_image)
        rest: list[_Cluster] = []
        for cluster in clusters:
            if cluster.box.expand(_CLUSTER_GAP).intersects(merged.box):
                merged.absorb(cluster)
            else:
                rest.append(cluster)
        rest.append(merged)
        clusters = rest
    changed = True
    while changed:  # clusters that grew into each other
        changed = False
        for i, a in enumerate(clusters):
            for j in range(i + 1, len(clusters)):
                if a.box.expand(_CLUSTER_GAP).intersects(clusters[j].box):
                    a.absorb(clusters.pop(j))
                    changed = True
                    break
            if changed:
                break
    return [c.box for c in clusters if c.image or c.ops >= _FIGURE_MIN_OPS]
