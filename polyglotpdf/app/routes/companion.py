"""Reading companion: conversations about passages, answered with Server-Sent Events.

``POST /api/companion/ask`` streams ``event: thread`` (the conversation and the
detected context), then ``event: delta`` pieces of the answer, and finally
``event: done`` or ``event: error``. Problems found before the model is called
(no AI engine configured, invalid question) are ordinary JSON errors.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from ...errors import CompanionError
from ..conversations import Message
from ..schemas import AskRequest
from ..state import AppState, PreparedQuestion, get_state

router = APIRouter(prefix="/api", tags=["companion"])
State = Annotated[AppState, Depends(get_state)]


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/documents/{document_id}/threads")
def list_threads(document_id: str, state: State) -> dict[str, Any]:
    state.library.get(document_id)
    threads = state.conversations.threads(document_id)
    return {"threads": [thread.to_dict(full=False) for thread in threads]}


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str, state: State) -> dict[str, Any]:
    return state.conversations.get(thread_id).to_dict()


@router.get("/threads/{thread_id}/context")
def thread_context(thread_id: str, state: State) -> dict[str, Any]:
    """Everything that was sent to the AI about the passage."""
    return state.conversations.get(thread_id).context.to_dict()


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: str, state: State) -> Response:
    state.conversations.delete(thread_id)
    return Response(status_code=204)


@router.post("/companion/ask")
async def ask(body: AskRequest, state: State) -> StreamingResponse:
    prepared = await run_in_threadpool(state.prepare_question, body)
    return StreamingResponse(
        _answer(state, prepared),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _answer(state: AppState, prepared: PreparedQuestion) -> AsyncIterator[str]:
    yield sse("thread", prepared.thread.to_dict())
    pieces: list[str] = []
    error: CompanionError | None = None
    interrupted = True
    message: Message | None = None
    try:
        async for piece in iterate_in_threadpool(prepared.stream):
            pieces.append(piece)
            yield sse("delta", {"text": piece})
        interrupted = False
    except CompanionError as exc:
        error = exc
    finally:
        _close(prepared)
        text = "".join(pieces)
        if text or (error is None and not interrupted):
            message = state.conversations.add_message(
                prepared.thread.id,
                "assistant",
                text,
                text,
                action=prepared.action,
                engine=prepared.client.name,
                model=prepared.client.model,
                status="complete" if error is None and not interrupted else "interrupted",
            )
    if error is not None:
        yield sse("error", {"message": str(error), "retryable": error.retryable})
    else:
        yield sse("done", {"message": message.to_dict() if message else None})


def _close(prepared: PreparedQuestion) -> None:
    close = getattr(prepared.stream, "close", None)
    try:
        if callable(close):
            close()  # stops the provider's HTTP stream when the reader cancels
    except ValueError:  # still running in the worker thread
        pass
    prepared.client.close()
