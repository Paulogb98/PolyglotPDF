"""Draw the application icon from the brand: the two quotes on the terracotta tile.

    uv run --with pillow --with fonttools --with brotli python scripts/make_icon.py

The opening quote is ink (the original), the closing one cream (the translation over
the terracotta). Below 20 px the pair closes up, so the small sizes keep only the
closing quote — the rule of the brand sheet. Writes the window/executable icon
(``src/polyglotpdf/app/assets/icon.ico`` and ``icon.png``) and the favicon.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "frontend" / "public" / "fonts" / "Caprasimo-400-latin.woff2"
ASSETS = ROOT / "src" / "polyglotpdf" / "app" / "assets"
FAVICON = ROOT / "frontend" / "public" / "favicon.png"

TERRACOTA = (198, 113, 57, 255)
INK = (46, 43, 37, 255)
CREAM = (255, 248, 240, 255)
BIG = 1024


def _font(size: int, ttf: Path) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ttf), size)


def tile(ttf: Path, *, pair: bool) -> Image.Image:
    """The icon at 1024 px; ``pair`` draws both quotes, otherwise only the closing one."""
    image = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, BIG - 1, BIG - 1), radius=int(BIG * 0.225), fill=TERRACOTA)
    glyphs = [("“", INK), ("”", CREAM)] if pair else [("”", CREAM)]
    target = BIG * (0.6 if pair else 0.34)  # the ink box the quotes should fill
    probe = _font(BIG, ttf)
    gap_ratio = 0.012

    def measure(font: ImageFont.FreeTypeFont) -> tuple[list[tuple[float, ...]], float, float]:
        boxes = [draw.textbbox((0, 0), glyph, font=font) for glyph, _ in glyphs]
        gap = font.size * gap_ratio
        width = sum(box[2] - box[0] for box in boxes) + gap * (len(boxes) - 1)
        height = max(box[3] for box in boxes) - min(box[1] for box in boxes)
        return boxes, width, height

    _, width, _ = measure(probe)
    font = _font(int(BIG * target / width), ttf)
    boxes, width, _ = measure(font)
    gap = font.size * gap_ratio
    # Draw on a layer of its own and centre what was actually inked: the quotes sit
    # high in their em box, so the font's metrics would leave them off centre.
    layer = Image.new("RGBA", (BIG * 2, BIG * 2), (0, 0, 0, 0))
    pen = ImageDraw.Draw(layer)
    x = BIG / 2
    for (glyph, colour), box in zip(glyphs, boxes, strict=True):
        pen.text((x - box[0], BIG / 2), glyph, font=font, fill=colour)
        x += box[2] - box[0] + gap
    ink = layer.crop(layer.getbbox())
    image.alpha_composite(ink, ((BIG - ink.width) // 2, (BIG - ink.height) // 2))
    return image


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        ttf = Path(folder) / "caprasimo.ttf"
        font = TTFont(str(FONT))
        font.flavor = None
        font.save(str(ttf))
        large = tile(ttf, pair=True)
        small = tile(ttf, pair=False)

    large.resize((512, 512), Image.LANCZOS).save(ASSETS / "icon.png")
    large.resize((64, 64), Image.LANCZOS).save(FAVICON)
    frames = [
        (small if size < 24 else large).resize((size, size), Image.LANCZOS)
        for size in (16, 20, 24, 32, 40, 48, 64, 128, 256)
    ]
    frames[-1].save(
        ASSETS / "icon.ico",
        format="ICO",
        sizes=[frame.size for frame in frames],
        append_images=frames[:-1],
    )
    print(f"icon: {ASSETS / 'icon.ico'}")


if __name__ == "__main__":
    main()
