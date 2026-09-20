"""Document-wide statistics used as a reference by the other heuristics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from ..model import DocumentStats, PageLayout
from .fonts import family_key, is_math_font, is_tex_text_font


def compute_stats(pages: Sequence[PageLayout]) -> DocumentStats:
    """Body font size and family, weighted by the number of letters they carry."""
    sizes: Counter[float] = Counter()
    families: Counter[str] = Counter()
    for page in pages:
        for block in page.blocks:
            for span in block.spans:
                letters = sum(1 for ch in span.chars if ch.c.isalpha())
                if not letters or is_math_font(span.font):
                    continue
                sizes[round(span.size * 2) / 2] += letters
                families[family_key(span.font)] += letters
    body_size = sizes.most_common(1)[0][0] if sizes else 10.0
    body_font = families.most_common(1)[0][0] if families else ""
    return DocumentStats(
        body_size=body_size, body_font=body_font, tex_body=is_tex_text_font(body_font)
    )
