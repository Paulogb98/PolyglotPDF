"""Tutor sessions of a document, their plans, and the per-document reading settings."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ..schemas import AnswerIn, DocSettingsIn
from ..state import AppState, get_state

router = APIRouter(prefix="/api/documents/{document_id}", tags=["tutor"])
State = Annotated[AppState, Depends(get_state)]


@router.get("/sessions")
def list_sessions(document_id: str, state: State, version: str | None = None) -> dict[str, Any]:
    sessions = state.sessions_of(document_id, version)
    current = state.sessions.current(document_id)
    settings = state.sessions.settings(document_id)
    return {
        "sessions": [session.to_dict() for session in sessions],
        "current": current.number if current else None,
        "settings": settings,
    }


@router.get("/sessions/{number}")
def get_session(
    document_id: str, number: int, state: State, version: str | None = None
) -> dict[str, Any]:
    state.sessions_of(document_id, version)
    return state.sessions.get(document_id, number).to_dict()


@router.post("/sessions/{number}/plan")
def plan_session(
    document_id: str, number: int, state: State, version: str | None = None, refresh: bool = False
) -> dict[str, Any]:
    """The tutor's plan for the session: what to expect, dense passages and questions.

    Generated once with the AI engine and stored; ``refresh=true`` asks for it again.
    """
    return state.plan_session(document_id, number, version, refresh=refresh).to_dict()


@router.post("/sessions/{number}/start")
def start_session(document_id: str, number: int, state: State) -> dict[str, Any]:
    return state.sessions.start(document_id, number).to_dict()


@router.post("/sessions/{number}/finish")
def finish_session(document_id: str, number: int, state: State) -> dict[str, Any]:
    session = state.sessions.finish(document_id, number)
    state.cards_from_session(document_id, session)
    return session.to_dict()


@router.post("/sessions/{number}/answer")
def answer_question(
    document_id: str, number: int, body: AnswerIn, state: State, version: str | None = None
) -> dict[str, Any]:
    """The reader's answer to a closing question, and the tutor's comment on it."""
    return state.check_answer(document_id, number, body.index, body.answer, version)


@router.get("/sessions/{number}/concepts")
def session_concepts(
    document_id: str, number: int, state: State, version: str | None = None
) -> dict[str, Any]:
    """The concept map at the end of the session (cumulative) and the reading pace."""
    return state.concept_map(document_id, number, version)


@router.get("/settings")
def get_settings(document_id: str, state: State) -> dict[str, Any]:
    state.library.get(document_id)
    return state.sessions.settings(document_id)


@router.put("/settings")
def update_settings(document_id: str, body: DocSettingsIn, state: State) -> dict[str, Any]:
    state.library.get(document_id)
    changes = {key: value for key, value in body.model_dump().items() if value is not None}
    return state.sessions.update_settings(document_id, changes)
