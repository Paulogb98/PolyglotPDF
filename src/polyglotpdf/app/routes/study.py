"""Study: highlights, annotations, bookmarks, the notebook, cards and reading time."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

from ..schemas import BookmarkIn, CardIn, MarkIn, MarkPatch, ReadingTimeIn, ReviewIn
from ..state import AppState, get_state
from ..study import COLORS

router = APIRouter(prefix="/api", tags=["study"])
State = Annotated[AppState, Depends(get_state)]


@router.get("/highlight-colors")
def colors() -> dict[str, Any]:
    return {
        "colors": [{"name": name, "ink": ink, "line": line} for name, (ink, line) in COLORS.items()]
    }


# ---------------------------------------------------------------------- marks
@router.get("/documents/{document_id}/marks")
def list_marks(
    document_id: str,
    state: State,
    page: int | None = None,
    kind: Annotated[str | None, Query(max_length=20)] = None,
    notebook: bool = False,
) -> dict[str, Any]:
    state.library.get(document_id)
    marks = state.study.marks(document_id, page=page, kind=kind, notebook_only=notebook)
    return {"marks": [mark.to_dict() for mark in marks]}


@router.post("/documents/{document_id}/marks", status_code=201)
def create_mark(document_id: str, body: MarkIn, state: State) -> dict[str, Any]:
    state.library.get(document_id)
    section = body.section or state.section_at(
        document_id, body.version_id, body.start.page, body.start.offset
    )
    mark = state.study.add_mark(
        document_id,
        version_id=body.version_id,
        kind="note" if (body.note or "").strip() else body.kind,
        color=body.color,
        quote=body.quote,
        note=body.note,
        tags=[tag.strip() for tag in body.tags if tag.strip()],
        start_page=body.start.page,
        start_offset=body.start.offset,
        end_page=body.end.page,
        end_offset=body.end.offset,
        section=list(section),
        source="tutor" if body.source == "tutor" else "reader",
        in_notebook=body.in_notebook,
    )
    return mark.to_dict()


@router.patch("/marks/{mark_id}")
def update_mark(mark_id: str, body: MarkPatch, state: State) -> dict[str, Any]:
    return state.study.update_mark(
        mark_id,
        color=body.color,
        note=body.note,
        tags=body.tags,
        kind=body.kind,
        in_notebook=body.in_notebook,
    ).to_dict()


@router.delete("/marks/{mark_id}", status_code=204)
def delete_mark(mark_id: str, state: State) -> Response:
    state.study.remove_mark(mark_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------- bookmarks
@router.get("/documents/{document_id}/bookmarks")
def list_bookmarks(document_id: str, state: State) -> dict[str, Any]:
    state.library.get(document_id)
    return {"bookmarks": state.study.bookmarks(document_id)}


@router.post("/documents/{document_id}/bookmarks")
def toggle_bookmark(document_id: str, body: BookmarkIn, state: State) -> dict[str, Any]:
    state.library.get(document_id)
    marked = state.study.toggle_bookmark(document_id, body.page, body.label)
    return {"page": body.page, "marked": marked, "bookmarks": state.study.bookmarks(document_id)}


# ---------------------------------------------------------------------- notebook
@router.get("/documents/{document_id}/notebook")
def notebook(document_id: str, state: State) -> dict[str, Any]:
    document = state.library.get(document_id)
    data = state.study.notebook(document_id).to_dict()
    data["document"] = {"id": document.id, "title": document.title, "authors": document.authors}
    data["reading_seconds"] = state.study.reading_time(document_id)
    data["reading_days"] = state.study.reading_days(document_id)
    return data


@router.post("/documents/{document_id}/reading-time")
def reading_time(document_id: str, body: ReadingTimeIn, state: State) -> dict[str, Any]:
    state.library.get(document_id)
    return {"seconds": state.study.add_reading_time(document_id, body.seconds)}


# ---------------------------------------------------------------------- cards
@router.get("/documents/{document_id}/cards")
def list_cards(document_id: str, state: State, due: bool = False) -> dict[str, Any]:
    state.library.get(document_id)
    cards = state.study.due_cards(document_id) if due else state.study.cards(document_id)
    return {"cards": [card.to_dict() for card in cards]}


@router.post("/documents/{document_id}/cards", status_code=201)
def create_card(document_id: str, body: CardIn, state: State) -> dict[str, Any]:
    state.library.get(document_id)
    card = state.study.add_card(
        document_id,
        front=body.front,
        back=body.back,
        quote=body.quote,
        page=body.page,
        mark_id=body.mark_id,
        source="tutor" if body.source == "tutor" else "reader",
    )
    return card.to_dict()


@router.get("/cards/{card_id}")
def get_card(card_id: str, state: State) -> dict[str, Any]:
    card = state.study.get_card(card_id)
    return {
        **card.to_dict(),
        "schedule": [option.to_dict() for option in state.study.schedule(card)],
    }


@router.post("/cards/{card_id}/review")
def review_card(card_id: str, body: ReviewIn, state: State) -> dict[str, Any]:
    return state.study.review(card_id, body.grade).to_dict()


@router.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: str, state: State) -> Response:
    state.study.remove_card(card_id)
    return Response(status_code=204)


@router.get("/documents/{document_id}/review")
def review_queue(document_id: str, state: State) -> dict[str, Any]:
    """The cards due now, each with what the four grades would do to it."""
    state.library.get(document_id)
    cards = state.study.due_cards(document_id)
    return {
        "cards": [
            {
                **card.to_dict(),
                "schedule": [option.to_dict() for option in state.study.schedule(card)],
            }
            for card in cards
        ],
        "counts": {
            "total": len(cards),
            "new": sum(1 for card in cards if card.state == "new"),
            "hard": sum(1 for card in cards if card.state == "hard"),
            "ok": sum(1 for card in cards if card.state == "ok"),
        },
    }
