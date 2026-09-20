"""Library: import, list, edit and remove documents; covers and files."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Response, UploadFile
from fastapi.responses import FileResponse

from ..library import NotFound
from ..schemas import DocumentPatch
from ..state import AppState, get_state

router = APIRouter(prefix="/api/documents", tags=["library"])
State = Annotated[AppState, Depends(get_state)]


@router.get("")
def list_documents(state: State, q: str | None = None, sort: str = "recent") -> dict[str, Any]:
    return {"documents": [document.to_dict() for document in state.library.documents(q, sort)]}


@router.post("", status_code=201)
def import_document(
    state: State, file: Annotated[UploadFile, File()], response: Response
) -> dict[str, Any]:
    filename = Path(file.filename or "documento.pdf").name
    folder = state.config.data_dir / "tmp"
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=folder, suffix=Path(filename).suffix, delete=False) as out:
        shutil.copyfileobj(file.file, out, length=1 << 20)
        temporary = Path(out.name)
    try:
        document, created = state.library.add(temporary, filename)
    finally:
        temporary.unlink(missing_ok=True)
    if not created:
        response.status_code = 200
    return {"document": document.to_dict(), "created": created}


@router.get("/{document_id}")
def get_document(document_id: str, state: State) -> dict[str, Any]:
    return state.library.get(document_id).to_dict()


@router.patch("/{document_id}")
def update_document(document_id: str, body: DocumentPatch, state: State) -> dict[str, Any]:
    return state.library.update(document_id, **body.model_dump()).to_dict()


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, state: State) -> Response:
    state.library.get(document_id)
    state.jobs.cancel_document(document_id)
    state.registry.close(document_id)
    state.library.remove(document_id)
    return Response(status_code=204)


@router.get("/{document_id}/cover")
def cover(document_id: str, state: State) -> FileResponse:
    path = state.library.cover_path(document_id)
    if not path.is_file():
        raise NotFound("No cover")
    return FileResponse(
        path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"}
    )


@router.get("/{document_id}/file")
def download(document_id: str, state: State, version: str | None = None) -> FileResponse:
    document = state.library.get(document_id)
    if version is None:
        return FileResponse(state.library.source_path(document_id), filename=document.filename)
    translation = state.library.version(document_id, version)
    name = f"{Path(document.filename).stem}.{translation.target_lang}.pdf"
    return FileResponse(state.library.reading_path(document_id, version), filename=name)


@router.delete("/{document_id}/versions/{version_id}", status_code=204)
def delete_version(document_id: str, version_id: str, state: State) -> Response:
    state.registry.close(document_id, version_id, all_versions=False)
    state.library.remove_version(document_id, version_id)
    return Response(status_code=204)
