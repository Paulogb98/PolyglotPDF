"""Persistent translation cache (SQLite).

Caching makes re-runs free, lets an interrupted translation of a long book resume
where it stopped and deduplicates repeated strings across documents. Entries are
keyed by everything that influences the result: engine fingerprint, languages,
glossary and the exact source markup.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path


def cache_key(*parts: str) -> str:
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TranslationCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS translations ("
                " key TEXT PRIMARY KEY,"
                " engine TEXT NOT NULL,"
                " source TEXT NOT NULL,"
                " target TEXT NOT NULL,"
                " created REAL NOT NULL)"
            )
            self._conn.commit()

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT target FROM translations WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def put(self, key: str, engine: str, source: str, target: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO translations (key, engine, source, target, created)"
                " VALUES (?, ?, ?, ?, ?)",
                (key, engine, source, target, time.time()),
            )
            self._conn.commit()

    def __len__(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> TranslationCache:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
