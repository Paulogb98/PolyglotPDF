"""Study material of a document: highlights, notes, bookmarks, cards and reading time.

Everything the reader makes on a page is a *mark*: a highlight (``kind='highlight'``)
or an annotation written on top of one (``kind='note'``). Marks are anchored the same
way conversations are — a start and an end (page, offset in code points of the page
text) — so the reader can jump back to the exact passage.

Review cards come from marks (and from the passages the tutor marked as dense) and are
scheduled with a small SM-2 variant; the four grades are the ones the interface shows:
*de novo*, *difícil*, *bom* and *fácil*.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ..errors import InputError
from .db import Database, now
from .i18n import msg
from .library import NotFound

#: Highlight colours of the interface, with the ink used for the underline.
COLORS: dict[str, tuple[str, str]] = {
    "amarelo": ("#e8c35a", "rgb(168 128 24 / .6)"),
    "verde": ("#a9c07b", "rgb(106 130 66 / .6)"),
    "coral": ("#e0937a", "rgb(178 98 45 / .6)"),
    "azul": ("#9db6c4", "rgb(93 130 150 / .6)"),
}

#: ``grade -> (interval multiplier, ease change)``; "again" restarts the card.
GRADES: dict[str, tuple[float, float]] = {
    "again": (0.0, -0.20),
    "hard": (1.2, -0.15),
    "good": (2.5, 0.0),
    "easy": (3.8, 0.15),
}
_AGAIN_MINUTES = 10
_FIRST_DAYS = {"hard": 1.0, "good": 4.0, "easy": 12.0}
_MIN_EASE = 1.3
_MAX_EASE = 3.2


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class Mark:
    id: str
    document_id: str
    version_id: str | None
    kind: str
    color: str
    quote: str
    note: str | None
    tags: list[str]
    start_page: int
    start_offset: int
    end_page: int
    end_offset: int
    section: list[str]
    source: str
    #: False: the highlight stays on the page but is left out of the notebook.
    in_notebook: bool
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "version_id": self.version_id,
            "kind": self.kind,
            "color": self.color,
            "quote": self.quote,
            "note": self.note,
            "tags": self.tags,
            "start": {"page": self.start_page, "offset": self.start_offset},
            "end": {"page": self.end_page, "offset": self.end_offset},
            "page": self.start_page,
            "section": self.section,
            "source": self.source,
            "in_notebook": self.in_notebook,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class Card:
    id: str
    document_id: str
    mark_id: str | None
    front: str
    back: str
    quote: str
    page: int
    source: str
    due_at: str
    interval_days: float
    ease: float
    reps: int
    lapses: int
    last_grade: str | None
    created_at: str
    updated_at: str

    @property
    def state(self) -> str:
        """``novo``, ``difícil`` or ``em dia`` — the three counters of the interface."""
        if self.reps == 0:
            return "new"
        if self.lapses > 0 and self.interval_days < 2:
            return "hard"
        return "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "mark_id": self.mark_id,
            "front": self.front,
            "back": self.back,
            "quote": self.quote,
            "page": self.page,
            "source": self.source,
            "due_at": self.due_at,
            "interval_days": round(self.interval_days, 3),
            "ease": round(self.ease, 3),
            "reps": self.reps,
            "lapses": self.lapses,
            "last_grade": self.last_grade,
            "state": self.state,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class Schedule:
    """What each grade would do to a card, shown on the four review buttons."""

    grade: str
    due_at: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {"grade": self.grade, "due_at": self.due_at, "label": self.label}


@dataclass(slots=True)
class Notebook:
    """Everything the reader made in one document, grouped by section."""

    marks: list[Mark]
    chapters: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    concepts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapters": self.chapters,
            "counts": self.counts,
            "concepts": self.concepts,
            "marks": [mark.to_dict() for mark in self.marks],
        }


class Study:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ marks
    def marks(
        self,
        document_id: str,
        *,
        page: int | None = None,
        kind: str | None = None,
        notebook_only: bool = False,
    ) -> list[Mark]:
        sql = "SELECT * FROM marks WHERE document_id = ?"
        params: list[Any] = [document_id]
        if notebook_only:
            sql += " AND in_notebook = 1"
        if page is not None:
            sql += " AND start_page <= ? AND end_page >= ?"
            params += [page, page]
        if kind == "tutor":
            sql += " AND source = 'tutor'"
        elif kind in {"highlight", "note"}:
            sql += " AND kind = ? AND source = 'reader'"
            params.append(kind)
        sql += " ORDER BY start_page, start_offset"
        return [_mark(row) for row in self.db.query(sql, params)]

    def page_marks(self, document_id: str, pages: list[int]) -> dict[int, list[Mark]]:
        """Marks touching any of ``pages``, grouped by the page they start on."""
        if not pages:
            return {}
        low, high = min(pages), max(pages)
        rows = self.db.query(
            "SELECT * FROM marks WHERE document_id = ? AND end_page >= ? AND start_page <= ?"
            " ORDER BY start_page, start_offset",
            (document_id, low, high),
        )
        grouped: dict[int, list[Mark]] = {page: [] for page in pages}
        for row in rows:
            mark = _mark(row)
            for page in range(mark.start_page, mark.end_page + 1):
                if page in grouped:
                    grouped[page].append(mark)
        return grouped

    def get_mark(self, mark_id: str) -> Mark:
        row = self.db.one("SELECT * FROM marks WHERE id = ?", (mark_id,))
        if row is None:
            raise NotFound(f"Mark {mark_id} not found")
        return _mark(row)

    def add_mark(
        self,
        document_id: str,
        *,
        version_id: str | None,
        kind: str,
        color: str,
        quote: str,
        note: str | None,
        tags: list[str],
        start_page: int,
        start_offset: int,
        end_page: int,
        end_offset: int,
        section: list[str],
        source: str = "reader",
        in_notebook: bool = True,
    ) -> Mark:
        if kind not in {"highlight", "note"}:
            raise InputError(f"Unknown mark kind {kind!r}")
        if color not in COLORS:
            raise InputError(f"Unknown highlight colour {color!r}")
        mark_id = uuid.uuid4().hex
        stamp = now()
        self.db.execute(
            "INSERT INTO marks (id, document_id, version_id, kind, color, quote, note, tags,"
            " start_page, start_offset, end_page, end_offset, section, source, in_notebook,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                mark_id,
                document_id,
                version_id,
                kind,
                color,
                quote.strip(),
                (note or "").strip() or None,
                json.dumps(tags, ensure_ascii=False),
                start_page,
                start_offset,
                end_page,
                end_offset,
                json.dumps(section, ensure_ascii=False),
                source,
                int(in_notebook),
                stamp,
                stamp,
            ),
        )
        return self.get_mark(mark_id)

    def update_mark(
        self,
        mark_id: str,
        *,
        color: str | None = None,
        note: str | None = None,
        tags: list[str] | None = None,
        kind: str | None = None,
        in_notebook: bool | None = None,
    ) -> Mark:
        mark = self.get_mark(mark_id)
        changes: dict[str, Any] = {}
        if in_notebook is not None:
            # Writing a note on a highlight always files it: a note with nowhere to
            # live would be lost.
            changes["in_notebook"] = int(in_notebook)
        if color is not None:
            if color not in COLORS:
                raise InputError(f"Unknown highlight colour {color!r}")
            changes["color"] = color
        if note is not None:
            text = note.strip()
            changes["note"] = text or None
            changes["kind"] = kind or ("note" if text else "highlight")
            if text:
                changes["in_notebook"] = 1
        elif kind is not None:
            changes["kind"] = kind
        if tags is not None:
            changes["tags"] = json.dumps(tags, ensure_ascii=False)
        if changes:
            changes["updated_at"] = now()
            columns = ", ".join(f"{name} = ?" for name in changes)
            self.db.execute(
                f"UPDATE marks SET {columns} WHERE id = ?", (*changes.values(), mark.id)
            )
        return self.get_mark(mark_id)

    def remove_mark(self, mark_id: str) -> None:
        self.get_mark(mark_id)
        self.db.execute("DELETE FROM marks WHERE id = ?", (mark_id,))

    # ------------------------------------------------------------------ bookmarks
    def bookmarks(self, document_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM bookmarks WHERE document_id = ? ORDER BY page", (document_id,)
        )
        return [
            {"page": row["page"], "label": row["label"], "created_at": row["created_at"]}
            for row in rows
        ]

    def toggle_bookmark(self, document_id: str, page: int, label: str = "") -> bool:
        """Adds or removes the ribbon on a page; returns whether it is now marked."""
        existing = self.db.one(
            "SELECT page FROM bookmarks WHERE document_id = ? AND page = ?", (document_id, page)
        )
        if existing is not None:
            self.db.execute(
                "DELETE FROM bookmarks WHERE document_id = ? AND page = ?", (document_id, page)
            )
            return False
        self.db.execute(
            "INSERT INTO bookmarks (document_id, page, label, created_at) VALUES (?, ?, ?, ?)",
            (document_id, page, label, now()),
        )
        return True

    # ------------------------------------------------------------------ cards
    def cards(self, document_id: str | None = None) -> list[Card]:
        if document_id:
            rows = self.db.query(
                "SELECT * FROM cards WHERE document_id = ? ORDER BY due_at", (document_id,)
            )
        else:
            rows = self.db.query("SELECT * FROM cards ORDER BY due_at")
        return [_card(row) for row in rows]

    def due_cards(self, document_id: str | None = None, *, limit: int = 60) -> list[Card]:
        moment = now()
        if document_id:
            rows = self.db.query(
                "SELECT * FROM cards WHERE document_id = ? AND due_at <= ? ORDER BY due_at LIMIT ?",
                (document_id, moment, limit),
            )
        else:
            rows = self.db.query(
                "SELECT * FROM cards WHERE due_at <= ? ORDER BY due_at LIMIT ?", (moment, limit)
            )
        return [_card(row) for row in rows]

    def get_card(self, card_id: str) -> Card:
        row = self.db.one("SELECT * FROM cards WHERE id = ?", (card_id,))
        if row is None:
            raise NotFound(f"Card {card_id} not found")
        return _card(row)

    def add_card(
        self,
        document_id: str,
        *,
        front: str,
        back: str,
        quote: str = "",
        page: int = 0,
        mark_id: str | None = None,
        source: str = "reader",
    ) -> Card:
        if not front.strip() or not back.strip():
            raise InputError("A card needs a question and an answer")
        card_id = uuid.uuid4().hex
        stamp = now()
        self.db.execute(
            "INSERT INTO cards (id, document_id, mark_id, front, back, quote, page, source,"
            " due_at, interval_days, ease, reps, lapses, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 2.5, 0, 0, ?, ?)",
            (
                card_id,
                document_id,
                mark_id,
                front.strip(),
                back.strip(),
                quote.strip(),
                page,
                source,
                stamp,
                stamp,
                stamp,
            ),
        )
        return self.get_card(card_id)

    def remove_card(self, card_id: str) -> None:
        self.get_card(card_id)
        self.db.execute("DELETE FROM cards WHERE id = ?", (card_id,))

    def schedule(self, card: Card, moment: datetime | None = None) -> list[Schedule]:
        """The four buttons of the review screen, each with when the card comes back."""
        moment = moment or datetime.now(UTC)
        options = []
        for grade in GRADES:
            due, days = _next_due(card, grade, moment)
            options.append(Schedule(grade, _iso(due), _interval_label(grade, days)))
        return options

    def review(self, card_id: str, grade: str) -> Card:
        if grade not in GRADES:
            raise InputError(f"Unknown grade {grade!r}; use {', '.join(GRADES)}")
        card = self.get_card(card_id)
        moment = datetime.now(UTC)
        due, days = _next_due(card, grade, moment)
        _multiplier, ease_change = GRADES[grade]
        ease = min(_MAX_EASE, max(_MIN_EASE, card.ease + ease_change))
        self.db.execute(
            "UPDATE cards SET due_at = ?, interval_days = ?, ease = ?, reps = reps + 1,"
            " lapses = lapses + ?, last_grade = ?, updated_at = ? WHERE id = ?",
            (
                _iso(due),
                days,
                ease,
                1 if grade == "again" else 0,
                grade,
                _iso(moment),
                card_id,
            ),
        )
        return self.get_card(card_id)

    # ------------------------------------------------------------------ notebook
    def notebook(self, document_id: str) -> Notebook:
        marks = self.marks(document_id, notebook_only=True)
        chapters: list[dict[str, Any]] = []
        index: dict[str, dict[str, Any]] = {}
        for mark in marks:
            title = mark.section[-1] if mark.section else ""  # the interface names it
            chapter = index.get(title)
            if chapter is None:
                chapter = {
                    "title": title,
                    "first_page": mark.start_page,
                    "last_page": mark.end_page,
                    "marks": [],
                }
                index[title] = chapter
                chapters.append(chapter)
            chapter["first_page"] = min(chapter["first_page"], mark.start_page)
            chapter["last_page"] = max(chapter["last_page"], mark.end_page)
            chapter["marks"].append(mark.to_dict())
        highlights = sum(1 for m in marks if m.source == "reader" and m.kind == "highlight")
        notes = sum(1 for m in marks if m.source == "reader" and m.kind == "note")
        tutor = sum(1 for m in marks if m.source == "tutor")
        cards = self.cards(document_id)
        due = self.due_cards(document_id)
        counts = {
            "total": len(marks),
            "highlights": highlights,
            "notes": notes,
            "tutor": tutor,
            "cards": len(cards),
            "due": len(due),
            "new": sum(1 for c in due if c.state == "new"),
            "hard": sum(1 for c in due if c.state == "hard"),
            "ok": sum(1 for c in due if c.state == "ok"),
        }
        return Notebook(marks=marks, chapters=chapters, counts=counts, concepts=_concepts(marks))

    # ------------------------------------------------------------------ reading time
    def add_reading_time(self, document_id: str, seconds: int) -> int:
        seconds = max(0, min(seconds, 3600))
        day = now()[:10]
        self.db.execute(
            "INSERT INTO reading_time (document_id, day, seconds) VALUES (?, ?, ?)"
            " ON CONFLICT(document_id, day) DO UPDATE SET seconds = seconds + excluded.seconds",
            (document_id, day, seconds),
        )
        return self.reading_time(document_id)

    def reading_days(self, document_id: str) -> int:
        row = self.db.one(
            "SELECT COUNT(*) AS days FROM reading_time WHERE document_id = ? AND seconds > 0",
            (document_id,),
        )
        return int(row["days"]) if row else 0

    def reading_time(self, document_id: str) -> int:
        row = self.db.one(
            "SELECT COALESCE(SUM(seconds), 0) AS total FROM reading_time WHERE document_id = ?",
            (document_id,),
        )
        return int(row["total"]) if row else 0


def _next_due(card: Card, grade: str, moment: datetime) -> tuple[datetime, float]:
    if grade == "again":
        return moment + timedelta(minutes=_AGAIN_MINUTES), 0.0
    if card.reps == 0 or card.interval_days <= 0:
        days = _FIRST_DAYS[grade]
    else:
        multiplier, _ = GRADES[grade]
        days = max(1.0, card.interval_days * multiplier * (card.ease / 2.5))
    days = min(days, 365.0)
    return moment + timedelta(days=days), days


def _interval_label(grade: str, days: float) -> str:
    if grade == "again":
        return msg("due.minutes", n=_AGAIN_MINUTES)
    if days < 1.5:
        return msg("due.tomorrow")
    if days < 30:
        return msg("due.days", n=round(days))
    months = round(days / 30)
    return msg("due.month") if months == 1 else msg("due.months", n=months)


def _concepts(marks: list[Mark], limit: int = 8) -> list[dict[str, Any]]:
    """Tags the reader wrote, most used first — the "conceitos que você marcou" list."""
    counts: dict[str, int] = {}
    for mark in marks:
        for tag in mark.tags:
            name = tag.strip().lower()
            if name:
                counts[name] = counts.get(name, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"name": name, "count": count} for name, count in ordered[:limit]]


def _mark(row: sqlite3.Row) -> Mark:
    return Mark(
        id=row["id"],
        document_id=row["document_id"],
        version_id=row["version_id"],
        kind=row["kind"],
        color=row["color"],
        quote=row["quote"],
        note=row["note"],
        tags=json.loads(row["tags"]),
        start_page=row["start_page"],
        start_offset=row["start_offset"],
        end_page=row["end_page"],
        end_offset=row["end_offset"],
        section=json.loads(row["section"]),
        source=row["source"],
        in_notebook=bool(row["in_notebook"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _card(row: sqlite3.Row) -> Card:
    return Card(
        id=row["id"],
        document_id=row["document_id"],
        mark_id=row["mark_id"],
        front=row["front"],
        back=row["back"],
        quote=row["quote"],
        page=row["page"],
        source=row["source"],
        due_at=row["due_at"],
        interval_days=row["interval_days"],
        ease=row["ease"],
        reps=row["reps"],
        lapses=row["lapses"],
        last_grade=row["last_grade"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


__all__ = ["COLORS", "GRADES", "Card", "Mark", "Notebook", "Schedule", "Study"]
