"""SQLite storage: documents, translations and reading-companion conversations.

One connection is shared by the request threads behind a lock (the application is
single-user and every statement is short). The schema is versioned with
``PRAGMA user_version``: append a script to :data:`MIGRATIONS` to evolve it.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE documents (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        authors TEXT,
        filename TEXT NOT NULL,
        format TEXT NOT NULL,
        pages INTEGER NOT NULL,
        size INTEGER NOT NULL,
        sha256 TEXT NOT NULL UNIQUE,
        added_at TEXT NOT NULL,
        opened_at TEXT,
        last_page INTEGER NOT NULL DEFAULT 0,
        favorite INTEGER NOT NULL DEFAULT 0,
        stats TEXT
    );
    CREATE TABLE versions (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        target_lang TEXT NOT NULL,
        engine TEXT NOT NULL,
        pages TEXT,
        created_at TEXT NOT NULL,
        report TEXT NOT NULL
    );
    CREATE INDEX versions_by_document ON versions(document_id, created_at);
    CREATE TABLE threads (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        version_id TEXT REFERENCES versions(id) ON DELETE SET NULL,
        quote TEXT NOT NULL,
        start_page INTEGER NOT NULL,
        start_offset INTEGER NOT NULL,
        end_page INTEGER NOT NULL,
        end_offset INTEGER NOT NULL,
        context TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX threads_by_document ON threads(document_id, updated_at);
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content TEXT NOT NULL,
        display TEXT NOT NULL,
        action TEXT,
        engine TEXT,
        model TEXT,
        status TEXT NOT NULL DEFAULT 'complete',
        created_at TEXT NOT NULL
    );
    CREATE INDEX messages_by_thread ON messages(thread_id, id);
    """,
    """
    CREATE TABLE marks (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        version_id TEXT,
        kind TEXT NOT NULL CHECK (kind IN ('highlight', 'note')),
        color TEXT NOT NULL DEFAULT 'yellow',
        quote TEXT NOT NULL,
        note TEXT,
        tags TEXT NOT NULL DEFAULT '[]',
        start_page INTEGER NOT NULL,
        start_offset INTEGER NOT NULL,
        end_page INTEGER NOT NULL,
        end_offset INTEGER NOT NULL,
        section TEXT NOT NULL DEFAULT '[]',
        source TEXT NOT NULL DEFAULT 'reader' CHECK (source IN ('reader', 'tutor')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX marks_by_document ON marks(document_id, start_page, start_offset);
    CREATE TABLE bookmarks (
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        page INTEGER NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        PRIMARY KEY (document_id, page)
    );
    CREATE TABLE cards (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        mark_id TEXT REFERENCES marks(id) ON DELETE SET NULL,
        front TEXT NOT NULL,
        back TEXT NOT NULL,
        quote TEXT NOT NULL DEFAULT '',
        page INTEGER NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT 'reader' CHECK (source IN ('reader', 'tutor')),
        due_at TEXT NOT NULL,
        interval_days REAL NOT NULL DEFAULT 0,
        ease REAL NOT NULL DEFAULT 2.5,
        reps INTEGER NOT NULL DEFAULT 0,
        lapses INTEGER NOT NULL DEFAULT 0,
        last_grade TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX cards_by_document ON cards(document_id, due_at);
    CREATE TABLE reading_time (
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        day TEXT NOT NULL,
        seconds INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (document_id, day)
    );
    CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        number INTEGER NOT NULL,
        title TEXT NOT NULL,
        start_page INTEGER NOT NULL,
        end_page INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'running', 'done')),
        plan TEXT,
        started_at TEXT,
        finished_at TEXT
    );
    CREATE UNIQUE INDEX sessions_by_document ON sessions(document_id, number);
    CREATE TABLE doc_settings (
        document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
        open_mode TEXT,
        layout TEXT,
        version_id TEXT,
        session_number INTEGER NOT NULL DEFAULT 1
    );
    """,
    """
    -- A highlight can stay on the page without entering the notebook
    -- ("When highlighting · keep in the notebook" in the reading settings).
    ALTER TABLE marks ADD COLUMN in_notebook INTEGER NOT NULL DEFAULT 1;
    """,
    """
    -- English became the project's language: the values stored for highlight colours
    -- and for the reader's layout were Portuguese until then ("coral" did not change).
    UPDATE marks SET color = 'yellow' WHERE color = 'amarelo';
    UPDATE marks SET color = 'green' WHERE color = 'verde';
    UPDATE marks SET color = 'blue' WHERE color = 'azul';
    UPDATE doc_settings SET layout = 'translation' WHERE layout = 'traducao';
    UPDATE doc_settings SET layout = 'side' WHERE layout = 'lado';
    """,
)


def now() -> str:
    """Current UTC time in ISO 8601 (sortable as text)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._migrate()

    def _migrate(self) -> None:
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            self._conn.executescript(f"BEGIN; {script} PRAGMA user_version = {number}; COMMIT;")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            row: sqlite3.Row | None = self._conn.execute(sql, params).fetchone()
            return row

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
