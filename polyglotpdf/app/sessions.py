"""Tutor sessions: stretches of a book read in one sitting, built from its outline.

A session is 10 to 15 pages that belong together. They come from the document's table
of contents when it has one — a chapter longer than the limit is split, several very
short ones are joined — and from plain page ranges when it has none. The tutor's plan
for a session (what to expect, the dense passages, the closing questions) is generated
on demand and stored, so reopening the book does not pay for it again.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from ..companion.tutor import plan_concepts, upgrade_plan
from ..reading.index import DocumentIndex
from .db import Database, now
from .i18n import msg
from .library import NotFound

TARGET_PAGES = 12
MIN_PAGES = 6
MAX_PAGES = 16
#: Characters of the session text sent to the tutor when it plans the session.
PLAN_CHARS = 18_000


@dataclass(slots=True)
class Session:
    id: str
    document_id: str
    number: int
    title: str
    start_page: int
    end_page: int
    status: str
    plan: dict[str, Any] | None
    started_at: str | None
    finished_at: str | None

    @property
    def pages(self) -> int:
        return self.end_page - self.start_page + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "number": self.number,
            "title": self.title,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "pages": self.pages,
            "status": self.status,
            "plan": self.plan,
            "has_plan": self.plan is not None,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class Sessions:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ building
    def ensure(self, document_id: str, index: DocumentIndex) -> list[Session]:
        """The sessions of a document, built from its outline the first time."""
        existing = self.list(document_id)
        if existing:
            return existing
        plan = build_ranges(index)
        with self.db.transaction() as conn:
            for number, (title, first, last) in enumerate(plan, start=1):
                conn.execute(
                    "INSERT INTO sessions (id, document_id, number, title, start_page,"
                    " end_page, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                    (uuid.uuid4().hex, document_id, number, title, first, last),
                )
            conn.execute(
                "INSERT INTO doc_settings (document_id, session_number) VALUES (?, 1)"
                " ON CONFLICT(document_id) DO NOTHING",
                (document_id,),
            )
        return self.list(document_id)

    def list(self, document_id: str) -> list[Session]:
        rows = self.db.query(
            "SELECT * FROM sessions WHERE document_id = ? ORDER BY number", (document_id,)
        )
        return [_session(row) for row in rows]

    def get(self, document_id: str, number: int) -> Session:
        row = self.db.one(
            "SELECT * FROM sessions WHERE document_id = ? AND number = ?", (document_id, number)
        )
        if row is None:
            raise NotFound(f"Session {number} not found")
        return _session(row)

    def at_page(self, document_id: str, page: int) -> Session | None:
        row = self.db.one(
            "SELECT * FROM sessions WHERE document_id = ? AND start_page <= ? AND end_page >= ?"
            " ORDER BY number LIMIT 1",
            (document_id, page, page),
        )
        return _session(row) if row else None

    def current(self, document_id: str) -> Session | None:
        row = self.db.one(
            "SELECT * FROM sessions WHERE document_id = ? AND status != 'done'"
            " ORDER BY number LIMIT 1",
            (document_id,),
        )
        return _session(row) if row else None

    # ------------------------------------------------------------------ progress
    def save_plan(self, document_id: str, number: int, plan: dict[str, Any]) -> Session:
        self.get(document_id, number)
        self.db.execute(
            "UPDATE sessions SET plan = ? WHERE document_id = ? AND number = ?",
            (json.dumps(plan, ensure_ascii=False), document_id, number),
        )
        return self.get(document_id, number)

    def start(self, document_id: str, number: int) -> Session:
        session = self.get(document_id, number)
        if session.status == "pending":
            self.db.execute(
                "UPDATE sessions SET status = 'running', started_at = ?"
                " WHERE document_id = ? AND number = ?",
                (now(), document_id, number),
            )
        return self.get(document_id, number)

    def finish(self, document_id: str, number: int) -> Session:
        self.get(document_id, number)
        self.db.execute(
            "UPDATE sessions SET status = 'done', finished_at = ?"
            " WHERE document_id = ? AND number = ?",
            (now(), document_id, number),
        )
        self.db.execute(
            "INSERT INTO doc_settings (document_id, session_number) VALUES (?, ?)"
            " ON CONFLICT(document_id) DO UPDATE SET session_number = excluded.session_number",
            (document_id, number + 1),
        )
        return self.get(document_id, number)

    # ------------------------------------------------------------------ per-document settings
    def settings(self, document_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM doc_settings WHERE document_id = ?", (document_id,))
        if row is None:
            return {"open_mode": None, "layout": None, "version_id": None, "session_number": 1}
        return {
            "open_mode": row["open_mode"],
            "layout": row["layout"],
            "version_id": row["version_id"],
            "session_number": row["session_number"],
        }

    def update_settings(self, document_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        current = self.settings(document_id)
        merged = {**current, **{k: v for k, v in changes.items() if k in current}}
        self.db.execute(
            "INSERT INTO doc_settings (document_id, open_mode, layout, version_id,"
            " session_number) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(document_id) DO UPDATE SET open_mode = excluded.open_mode,"
            " layout = excluded.layout, version_id = excluded.version_id,"
            " session_number = excluded.session_number",
            (
                document_id,
                merged["open_mode"],
                merged["layout"],
                merged["version_id"],
                int(merged["session_number"] or 1),
            ),
        )
        return self.settings(document_id)


def build_ranges(index: DocumentIndex) -> list[tuple[str, int, int]]:
    """``(title, first page, last page)`` of every session, 0-based and contiguous."""
    total = index.page_count
    if total <= 0:
        return []
    entries = [entry for entry in index.info().toc if entry.level <= 2]
    starts: list[tuple[str, int]] = []
    for entry in entries:
        page = max(0, min(entry.page, total - 1))
        if starts and starts[-1][1] == page:
            continue
        starts.append((entry.title.strip() or f"p. {page + 1}", page))
    if not starts or starts[0][1] > 0:
        starts.insert(0, (msg("session.beginning"), 0))

    chunks: list[tuple[str, int, int]] = []
    for position, (title, first) in enumerate(starts):
        last = (starts[position + 1][1] - 1) if position + 1 < len(starts) else total - 1
        if last < first:
            continue
        chunks.append((title, first, last))
    return _split_and_join(chunks, total)


def _split_and_join(chunks: list[tuple[str, int, int]], total: int) -> list[tuple[str, int, int]]:
    parts: list[tuple[str, int, int]] = []
    for title, first, last in chunks:
        length = last - first + 1
        if length <= MAX_PAGES:
            parts.append((title, first, last))
            continue
        pieces = max(1, round(length / TARGET_PAGES))
        size = -(-length // pieces)  # ceiling division
        for number in range(pieces):
            start = first + number * size
            stop = min(last, start + size - 1)
            if start > last:
                break
            name = title if pieces == 1 else f"{title} ({number + 1}/{pieces})"
            parts.append((name, start, stop))

    joined: list[tuple[str, int, int]] = []
    for title, first, last in parts:
        if joined and (last - joined[-1][1] + 1) <= MAX_PAGES and (last - first + 1) < MIN_PAGES:
            previous = joined[-1]
            joined[-1] = (previous[0], previous[1], last)
            continue
        joined.append((title, first, last))
    if not joined:
        joined = [(msg("session.reading"), 0, max(0, total - 1))]
    return joined


def session_text(index: DocumentIndex, session: Session, limit: int = PLAN_CHARS) -> str:
    """The text of the session's pages, cut at ``limit`` characters."""
    pieces: list[str] = []
    size = 0
    for page in range(session.start_page, session.end_page + 1):
        if page >= index.page_count:
            break
        text = index.page_text(page).clean().strip()
        if not text:
            continue
        piece = f"[p. {index.page_label(page)}]\n{text}"
        if size + len(piece) > limit:
            pieces.append(piece[: max(0, limit - size)])
            break
        pieces.append(piece)
        size += len(piece)
    return "\n\n".join(pieces)


@dataclass(slots=True)
class ConceptEntry:
    """A concept of the book as the tutor's plans met it, session after session."""

    name: str
    term: str
    definition: str
    session: int  # the session that introduced it
    sessions: list[int]  # every session whose plan lists it

    @property
    def needle(self) -> str:
        """What to look for in the book: the text's own word, else the name."""
        return self.term or self.name


def concept_history(sessions: list[Session]) -> list[ConceptEntry]:
    """Every concept of the planned sessions, in the order the reader meets them.

    The tutor keeps the name of a concept that comes back; a concept renamed but with the
    same word in the text is still the same one.
    """
    entries: dict[str, ConceptEntry] = {}
    by_term: dict[str, str] = {}
    for session in sorted(sessions, key=lambda item: item.number):
        for concept in plan_concepts((session.plan or {}).get("concepts")):
            name, term, definition = concept["name"], concept["term"], concept["definition"]
            key = name.casefold()
            if key not in entries and term.casefold() in by_term:
                key = by_term[term.casefold()]
            entry = entries.get(key)
            if entry is None:
                entry = entries[key] = ConceptEntry(name, term, definition, session.number, [])
            else:
                entry.term = entry.term or term
                entry.definition = entry.definition or definition
            if term:
                by_term.setdefault(term.casefold(), key)
            if session.number not in entry.sessions:
                entry.sessions.append(session.number)
    return list(entries.values())


def known_before(sessions: list[Session], number: int, limit: int = 40) -> list[str]:
    """The concepts met before session ``number``, as the tutor's plan message lists them."""
    earlier = [entry for entry in concept_history(sessions) if entry.session < number]
    shown = []
    for entry in earlier[-limit:]:
        same = not entry.term or entry.term.casefold() == entry.name.casefold()
        shown.append(entry.name if same else f"{entry.name} ({entry.term})")
    return shown


def pace(
    sessions: list[Session],
    number: int,
    sections: list[tuple[str, int]],
    seconds: int,
    page_count: int,
) -> dict[str, Any]:
    """How much is left after session ``number``, and how long it takes at the reader's pace.

    ``sections`` are the book's top-level parts, ``(title, first page)``: when the book has
    several, the projection is for the part the session belongs to. The pace is the reading
    time over the pages of the sessions already done.
    """
    current = next((item for item in sessions if item.number == number), None)
    later = [item for item in sessions if item.number > number and item.status != "done"]
    done_pages = sum(item.pages for item in sessions if item.status == "done")
    per_page = seconds / done_pages if done_pages and seconds >= 60 else None

    scope, title, left = "book", None, later
    parts = sorted(sections, key=lambda part: part[1])
    if current is not None and len(parts) >= 2:
        holding = [part for part in parts if part[1] <= current.start_page]
        if holding:
            name, first = holding[-1]
            end = next((page for _, page in parts if page > first), page_count)
            in_part = [item for item in later if item.start_page < end]
            if in_part:
                scope, title, left = "section", name, in_part
    if not left:
        scope, title = "done", None
    minutes = round(per_page * sum(item.pages for item in left) / 60) if per_page else None
    return {"scope": scope, "title": title, "sessions_left": len(left), "minutes_left": minutes}


def _session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        document_id=row["document_id"],
        number=row["number"],
        title=row["title"],
        start_page=row["start_page"],
        end_page=row["end_page"],
        status=row["status"],
        plan=upgrade_plan(json.loads(row["plan"])) if row["plan"] else None,
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


__all__ = [
    "MAX_PAGES",
    "MIN_PAGES",
    "TARGET_PAGES",
    "ConceptEntry",
    "Session",
    "Sessions",
    "build_ranges",
    "concept_history",
    "known_before",
    "pace",
    "session_text",
]
