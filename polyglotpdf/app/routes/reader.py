"""Reader: page geometry and outline, page images, text layer, search and passage context."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

from ...reading.context import Anchor, build_context
from ...reading.index import DocumentIndex
from ..conversations import context_summary
from ..library import NotFound
from ..schemas import ContextRequest
from ..state import AppState, get_state

router = APIRouter(prefix="/api/documents/{document_id}", tags=["reader"])
State = Annotated[AppState, Depends(get_state)]
_IMMUTABLE = {"Cache-Control": "private, max-age=604800, immutable"}


def _page(index: DocumentIndex, page: int) -> int:
    if not 0 <= page < index.page_count:
        raise NotFound(f"Page {page} is outside 0-{index.page_count - 1}")
    return page


@router.get("/layout")
def layout(document_id: str, state: State, version: str | None = None) -> dict[str, Any]:
    index = state.registry.get(document_id, version)
    info = index.info()
    return {
        "page_count": index.page_count,
        "pages": [[round(w, 2), round(h, 2)] for w, h in index.page_sizes()],
        "title": info.title,
        "authors": info.authors,
        "language": index.language(),
        "toc": info.to_dict()["toc"],
    }


@router.get("/pages/{page}/image")
def page_image(
    document_id: str,
    page: int,
    state: State,
    scale: Annotated[float, Query(ge=0.1, le=5.0)] = 1.5,
    version: str | None = None,
) -> Response:
    index = state.registry.get(document_id, version)
    data = index.render(_page(index, page), scale)
    return Response(data, media_type="image/png", headers=_IMMUTABLE)


@router.get("/pages/{page}/text")
def page_text(
    document_id: str, page: int, state: State, version: str | None = None
) -> dict[str, Any]:
    index = state.registry.get(document_id, version)
    layer = index.page_text(_page(index, page)).to_layer()
    layer["label"] = index.page_label(page)
    return layer


@router.get("/search")
def search(
    document_id: str,
    state: State,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    version: str | None = None,
) -> dict[str, Any]:
    hits = state.registry.get(document_id, version).search(q)
    return {
        "query": q,
        "total": sum(len(boxes) for _, boxes in hits),
        "hits": [
            {"page": page, "rects": [[round(v, 2) for v in box.as_tuple()] for box in boxes]}
            for page, boxes in hits
        ],
    }


@router.post("/context")
def passage_context(document_id: str, body: ContextRequest, state: State) -> dict[str, Any]:
    """The context the reading companion would send for a selection (or a page)."""
    index = state.registry.get(document_id, body.version_id)
    start = Anchor(body.start.page, body.start.offset)
    end = Anchor(body.end.page, body.end.offset) if body.end else None
    context = build_context(index, start, end, size=state.preferences.get().context_size)
    return {
        **context_summary(context),
        "before": context.before,
        "current": context.current,
        "after": context.after,
        "start": {"page": context.start.page, "offset": context.start.offset},
        "end": {"page": context.end.page, "offset": context.end.offset},
    }
