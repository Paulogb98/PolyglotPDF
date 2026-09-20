"""Engines, API keys, languages, preferences and application information."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends

from ... import __version__
from ...companion import list_actions
from ...translation.engines import get_engine
from ...translation.languages import list_languages
from ...translation.registry import check_engine, list_models
from ..library import SUPPORTED
from ..schemas import CheckIn, KeyIn
from ..state import AppState, get_state

router = APIRouter(prefix="/api", tags=["settings"])
State = Annotated[AppState, Depends(get_state)]


@router.get("/info")
def info(state: State) -> dict[str, Any]:
    return {
        "version": __version__,
        "data_dir": str(state.config.data_dir),
        "formats": sorted(SUPPORTED),
        "secret_store": state.secrets.description,
    }


@router.get("/engines")
def engines(state: State) -> dict[str, Any]:
    return {"engines": state.engines_view(), "companion_engine": state.companion_engine()}


@router.put("/engines/{name}/key")
def set_key(name: str, body: KeyIn, state: State) -> dict[str, Any]:
    info = get_engine(name)
    state.secrets.set(info.name, body.api_key.strip())
    return state.engine_view(info.name)


@router.delete("/engines/{name}/key")
def delete_key(name: str, state: State) -> dict[str, Any]:
    info = get_engine(name)
    state.secrets.delete(info.name)
    return state.engine_view(info.name)


@router.post("/engines/{name}/check")
def check(name: str, body: CheckIn, state: State) -> dict[str, Any]:
    """One cheap request to the provider (lists models); never translates anything."""
    info = get_engine(name)
    base_url = body.base_url or state.preferences.get().engine(info.name).base_url
    result = check_engine(info.name, body.api_key or state.api_key(info.name), base_url)
    return {"ok": result.ok, "message": result.message, "models": result.models}


@router.get("/engines/{name}/models")
def models(name: str, state: State) -> dict[str, Any]:
    info = get_engine(name)
    base_url = state.preferences.get().engine(info.name).base_url
    return {"models": list_models(info.name, state.api_key(info.name), base_url)}


@router.get("/languages")
def languages() -> dict[str, Any]:
    return {"languages": [{"code": code, "name": name} for code, name in list_languages()]}


@router.get("/preferences")
def get_preferences(state: State) -> dict[str, Any]:
    return state.preferences.get().to_dict()


@router.put("/preferences")
def update_preferences(state: State, changes: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    return state.preferences.update(changes).to_dict()


@router.get("/companion/actions")
def actions() -> dict[str, Any]:
    return {"actions": [{"key": a.key, "label": a.label} for a in list_actions()]}
