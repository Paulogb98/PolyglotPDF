"""The word the reader tapped: its senses, the sense it has in this book, and its uses."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from ..state import AppState, get_state

router = APIRouter(prefix="/api/documents/{document_id}", tags=["dictionary"])
State = Annotated[AppState, Depends(get_state)]


@router.get("/dictionary")
def dictionary(
    document_id: str,
    state: State,
    word: Annotated[str, Query(min_length=1, max_length=80)],
    page: Annotated[int, Query(ge=0)] = 0,
    offset: Annotated[int, Query(ge=0)] = 0,
    version: str | None = None,
) -> dict[str, Any]:
    return state.dictionary_entry(document_id, word, page, offset, version)
