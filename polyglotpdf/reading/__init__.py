"""Reading support: page text with selectable words, document structure and passage context.

Used by the reader application (text layer, outline, search) and by the reading
companion (what surrounds a selected passage). It reuses the analysis of the
translation pipeline, so offsets, blocks and paragraphs are the same everywhere.
"""

from .context import CONTEXT_SIZES, Anchor, PassageContext, build_context
from .index import MUPDF_LOCK, DocumentIndex, DocumentInfo, TocEntry
from .text import PageText, TextBlock, Word, build_page_text, join_lines

__all__ = [
    "CONTEXT_SIZES",
    "MUPDF_LOCK",
    "Anchor",
    "DocumentIndex",
    "DocumentInfo",
    "PageText",
    "PassageContext",
    "TextBlock",
    "TocEntry",
    "Word",
    "build_context",
    "build_page_text",
    "join_lines",
]
