"""Translations and estimates running in the background."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ..jobs import Job
from ..library import NotFound
from ..schemas import EstimateRequest, TranslateRequest
from ..state import AppState, get_state

router = APIRouter(prefix="/api", tags=["jobs"])
State = Annotated[AppState, Depends(get_state)]


def _job(state: AppState, job_id: str) -> Job:
    try:
        return state.jobs.get(job_id)
    except KeyError:
        raise NotFound(f"Job {job_id} not found") from None


@router.post("/documents/{document_id}/translate", status_code=202)
def translate(document_id: str, body: TranslateRequest, state: State) -> dict[str, Any]:
    return state.start_translation(document_id, body).to_dict()


@router.post("/documents/{document_id}/estimate", status_code=202)
def estimate(document_id: str, body: EstimateRequest, state: State) -> dict[str, Any]:
    return state.start_estimate(document_id, body.pages).to_dict()


@router.get("/jobs")
def list_jobs(state: State, document_id: str | None = None) -> dict[str, Any]:
    return {"jobs": [job.to_dict() for job in state.jobs.list(document_id)]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, state: State) -> dict[str, Any]:
    return _job(state, job_id).to_dict()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, state: State) -> dict[str, Any]:
    _job(state, job_id)
    return state.jobs.cancel(job_id).to_dict()
