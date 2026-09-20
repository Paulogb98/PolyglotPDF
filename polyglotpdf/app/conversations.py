"""Reading-companion conversations: one thread per passage, stored with its context."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..companion.chat import ChatMessage, Role
from ..reading.context import Anchor, PassageContext
from .db import Database, now
from .i18n import msg
from .library import NotFound


@dataclass(slots=True)
class Message:
    id: int
    role: Role
    content: str  # what the model received or produced
    display: str  # what the interface shows (the question or the action name)
    action: str | None
    engine: str | None
    model: str | None
    status: str  # "complete" or "interrupted"
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "text": self.display,
            "action": self.action,
            "engine": self.engine,
            "model": self.model,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class Thread:
    id: str
    document_id: str
    version_id: str | None
    quote: str
    context: PassageContext
    created_at: str
    updated_at: str
    messages: list[Message] = field(default_factory=list)
    message_count: int = 0

    @property
    def start(self) -> Anchor:
        return self.context.start

    @property
    def end(self) -> Anchor:
        return self.context.end

    def to_dict(self, *, full: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "document_id": self.document_id,
            "version_id": self.version_id,
            "quote": self.quote,
            "page": self.context.page,
            "page_label": self.context.page_label,
            "whole_page": self.context.whole_page,
            "start": {"page": self.start.page, "offset": self.start.offset},
            "end": {"page": self.end.page, "offset": self.end.offset},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": self.message_count or len(self.messages),
        }
        if full:
            data["context"] = context_summary(self.context)
            data["messages"] = [message.to_dict() for message in self.messages]
        return data


def context_summary(context: PassageContext) -> dict[str, Any]:
    """What the interface shows about the context sent to the AI."""
    return {
        "title": context.title,
        "authors": context.authors,
        "section": list(context.section),
        "page": context.page,
        "page_label": context.page_label,
        "page_count": context.page_count,
        "selection": context.selection,
        "whole_page": context.whole_page,
        "characters": {
            "before": len(context.before),
            "current": len(context.current),
            "after": len(context.after),
        },
    }


class Conversations:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, document_id: str, version_id: str | None, context: PassageContext) -> Thread:
        thread_id = uuid.uuid4().hex
        stamp = now()
        quote = context.selection[:600] or msg("thread.page", page=context.page_label)
        self.db.execute(
            "INSERT INTO threads (id, document_id, version_id, quote, start_page, start_offset,"
            " end_page, end_offset, context, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                thread_id,
                document_id,
                version_id,
                quote,
                context.start.page,
                context.start.offset,
                context.end.page,
                context.end.offset,
                json.dumps(context.to_dict(), ensure_ascii=False),
                stamp,
                stamp,
            ),
        )
        return self.get(thread_id)

    def get(self, thread_id: str) -> Thread:
        row = self.db.one("SELECT * FROM threads WHERE id = ?", (thread_id,))
        if row is None:
            raise NotFound(f"Conversation {thread_id} not found")
        thread = _thread(row)
        rows = self.db.query("SELECT * FROM messages WHERE thread_id = ? ORDER BY id", (thread_id,))
        thread.messages = [_message(message) for message in rows]
        thread.message_count = len(thread.messages)
        return thread

    def threads(self, document_id: str) -> list[Thread]:
        rows = self.db.query(
            "SELECT t.*, (SELECT COUNT(*) FROM messages m WHERE m.thread_id = t.id) AS n"
            " FROM threads t WHERE t.document_id = ? ORDER BY t.updated_at DESC",
            (document_id,),
        )
        threads = []
        for row in rows:
            thread = _thread(row)
            thread.message_count = int(row["n"])
            threads.append(thread)
        return threads

    def add_message(
        self,
        thread_id: str,
        role: Role,
        content: str,
        display: str,
        *,
        action: str | None = None,
        engine: str | None = None,
        model: str | None = None,
        status: str = "complete",
    ) -> Message:
        stamp = now()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (thread_id, role, content, display, action, engine, model,"
                " status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (thread_id, role, content, display, action, engine, model, status, stamp),
            )
            conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (stamp, thread_id))
            message_id = int(cursor.lastrowid or 0)
        row = self.db.one("SELECT * FROM messages WHERE id = ?", (message_id,))
        assert row is not None
        return _message(row)

    def history(self, thread_id: str) -> list[ChatMessage]:
        """The turns to send before a follow-up question (interrupted answers included)."""
        return [ChatMessage(m.role, m.content) for m in self.get(thread_id).messages if m.content]

    def delete(self, thread_id: str) -> None:
        self.get(thread_id)
        self.db.execute("DELETE FROM threads WHERE id = ?", (thread_id,))


def _thread(row: sqlite3.Row) -> Thread:
    return Thread(
        id=row["id"],
        document_id=row["document_id"],
        version_id=row["version_id"],
        quote=row["quote"],
        context=PassageContext.from_dict(json.loads(row["context"])),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        role=row["role"],
        content=row["content"],
        display=row["display"],
        action=row["action"],
        engine=row["engine"],
        model=row["model"],
        status=row["status"],
        created_at=row["created_at"],
    )
