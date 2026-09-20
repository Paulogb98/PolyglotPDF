"""The library: imported documents, their files and their translations.

Files live in ``<data dir>/documents/<id>/``: the imported file (``source.<ext>``), a
PDF reading copy for e-book formats (``reading.pdf``), the cover and one PDF per
translation (``versions/<version id>.pdf``). Identical files are imported once
(SHA-256).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..errors import InputError
from ..model import DocumentStats
from ..pdf.loader import CONVERTIBLE, load_pdf_bytes
from ..reading.index import MUPDF_LOCK, DocumentIndex
from .db import Database, now

SUPPORTED = frozenset({".pdf", *CONVERTIBLE})
COVER_WIDTH = 360
_SORTS = {
    "recent": "COALESCE(opened_at, added_at) DESC",
    "added": "added_at DESC",
    "title": "title COLLATE NOCASE ASC",
}


class NotFound(LookupError):
    """A document, translation or conversation that does not exist."""


@dataclass(slots=True)
class Version:
    id: str
    document_id: str
    target_lang: str
    engine: str
    pages: list[int] | None  # 0-based pages translated; None = all
    created_at: str
    report: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        report = self.report
        return {
            "id": self.id,
            "target_lang": self.target_lang,
            "engine": self.engine,
            "pages": self.pages,
            "created_at": self.created_at,
            "translated": report.get("translated"),
            "failed": report.get("failed"),
            "warnings": report.get("warnings", []),
        }


@dataclass(slots=True)
class Document:
    id: str
    title: str
    authors: str | None
    filename: str
    format: str
    pages: int
    size: int
    sha256: str
    added_at: str
    opened_at: str | None
    last_page: int
    favorite: bool
    stats: DocumentStats | None = None
    versions: list[Version] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "authors": self.authors,
            "filename": self.filename,
            "format": self.format,
            "pages": self.pages,
            "size": self.size,
            "added_at": self.added_at,
            "opened_at": self.opened_at,
            "last_page": self.last_page,
            "progress": round((self.last_page + 1) / self.pages, 4) if self.opened_at else 0.0,
            "favorite": self.favorite,
            "versions": [version.to_dict() for version in self.versions],
        }


class Library:
    def __init__(self, db: Database, root: Path) -> None:
        self.db = db
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ import
    def add(self, source: Path, filename: str) -> tuple[Document, bool]:
        """Import a file; returns the document and whether it is new (False: already there)."""
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED:
            supported = ", ".join(sorted(SUPPORTED))
            raise InputError(f"Unsupported file type {suffix or '(none)'}; supported: {supported}")
        digest = _sha256(source)
        existing = self.db.one("SELECT id FROM documents WHERE sha256 = ?", (digest,))
        if existing is not None:
            return self.get(existing["id"]), False

        document_id = uuid.uuid4().hex
        folder = self.root / document_id
        folder.mkdir(parents=True)
        try:
            stored = folder / f"source{suffix}"
            shutil.copyfile(source, stored)
            reading = stored
            if suffix != ".pdf":
                with MUPDF_LOCK:
                    data = load_pdf_bytes(stored)
                reading = folder / "reading.pdf"
                reading.write_bytes(data)
            index = DocumentIndex.open(reading, name=Path(filename).stem)
            try:
                info = index.info()
                stats = index.stats
                width = index.page_sizes()[0][0] or 600.0
                (folder / "cover.png").write_bytes(index.render(0, COVER_WIDTH / width))
            finally:
                index.close()
            self.db.execute(
                "INSERT INTO documents (id, title, authors, filename, format, pages, size, sha256,"
                " added_at, stats) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    info.title,
                    info.authors,
                    Path(filename).name,
                    suffix.lstrip("."),
                    info.page_count,
                    stored.stat().st_size,
                    digest,
                    now(),
                    json.dumps(asdict(stats)),
                ),
            )
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return self.get(document_id), True

    # ------------------------------------------------------------------ queries
    def documents(self, query: str | None = None, sort: str = "recent") -> list[Document]:
        order = _SORTS.get(sort, _SORTS["recent"])
        if query and query.strip():
            pattern = f"%{query.strip()}%"
            rows = self.db.query(
                "SELECT * FROM documents WHERE title LIKE ? OR authors LIKE ? OR filename LIKE ?"
                f" ORDER BY favorite DESC, {order}",
                (pattern, pattern, pattern),
            )
        else:
            rows = self.db.query(f"SELECT * FROM documents ORDER BY favorite DESC, {order}")
        versions = self._versions([row["id"] for row in rows])
        return [_document(row, versions.get(row["id"], [])) for row in rows]

    def get(self, document_id: str) -> Document:
        row = self.db.one("SELECT * FROM documents WHERE id = ?", (document_id,))
        if row is None:
            raise NotFound(f"Document {document_id} not found")
        return _document(row, self._versions([document_id]).get(document_id, []))

    def update(
        self,
        document_id: str,
        *,
        title: str | None = None,
        authors: str | None = None,
        last_page: int | None = None,
        favorite: bool | None = None,
        opened: bool = False,
    ) -> Document:
        document = self.get(document_id)
        changes: dict[str, Any] = {}
        if title is not None and title.strip():
            changes["title"] = " ".join(title.split())
        if authors is not None:
            changes["authors"] = " ".join(authors.split()) or None
        if last_page is not None:
            changes["last_page"] = min(max(0, last_page), document.pages - 1)
        if favorite is not None:
            changes["favorite"] = int(favorite)
        if opened:
            changes["opened_at"] = now()
        if changes:
            columns = ", ".join(f"{name} = ?" for name in changes)
            self.db.execute(
                f"UPDATE documents SET {columns} WHERE id = ?", (*changes.values(), document_id)
            )
        return self.get(document_id)

    def remove(self, document_id: str) -> None:
        self.get(document_id)
        self.db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        shutil.rmtree(self.root / document_id, ignore_errors=True)

    def save_stats(self, document_id: str, stats: DocumentStats) -> None:
        self.db.execute(
            "UPDATE documents SET stats = ? WHERE id = ?", (json.dumps(asdict(stats)), document_id)
        )

    # ------------------------------------------------------------------ files
    def folder(self, document_id: str) -> Path:
        return self.root / document_id

    def source_path(self, document_id: str) -> Path:
        document = self.get(document_id)
        return self.folder(document_id) / f"source.{document.format}"

    def reading_path(self, document_id: str, version_id: str | None = None) -> Path:
        """The PDF shown in the reader: the original (or its PDF copy) or a translation."""
        folder = self.folder(document_id)
        if version_id is not None:
            self.version(document_id, version_id)
            return folder / "versions" / f"{version_id}.pdf"
        converted = folder / "reading.pdf"
        return converted if converted.is_file() else self.source_path(document_id)

    def cover_path(self, document_id: str) -> Path:
        return self.folder(document_id) / "cover.png"

    # ------------------------------------------------------------------ translations
    def new_version(self, document_id: str) -> tuple[str, Path]:
        """Allocate an id and an output path for a translation of the document."""
        self.get(document_id)
        version_id = uuid.uuid4().hex
        folder = self.folder(document_id) / "versions"
        folder.mkdir(parents=True, exist_ok=True)
        return version_id, folder / f"{version_id}.pdf"

    def add_version(
        self,
        document_id: str,
        version_id: str,
        *,
        target_lang: str,
        engine: str,
        pages: list[int] | None,
        report: dict[str, Any],
    ) -> Version:
        self.db.execute(
            "INSERT INTO versions (id, document_id, target_lang, engine, pages, created_at, report)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                version_id,
                document_id,
                target_lang,
                engine,
                json.dumps(pages) if pages is not None else None,
                now(),
                json.dumps(report, ensure_ascii=False),
            ),
        )
        return self.version(document_id, version_id)

    def version(self, document_id: str, version_id: str) -> Version:
        row = self.db.one(
            "SELECT * FROM versions WHERE id = ? AND document_id = ?", (version_id, document_id)
        )
        if row is None:
            raise NotFound(f"Translation {version_id} not found")
        return _version(row)

    def remove_version(self, document_id: str, version_id: str) -> None:
        self.version(document_id, version_id)
        self.db.execute("DELETE FROM versions WHERE id = ?", (version_id,))
        (self.folder(document_id) / "versions" / f"{version_id}.pdf").unlink(missing_ok=True)

    def _versions(self, document_ids: list[str]) -> dict[str, list[Version]]:
        if not document_ids:
            return {}
        marks = ", ".join("?" for _ in document_ids)
        rows = self.db.query(
            f"SELECT * FROM versions WHERE document_id IN ({marks}) ORDER BY created_at DESC",
            document_ids,
        )
        grouped: dict[str, list[Version]] = {}
        for row in rows:
            grouped.setdefault(row["document_id"], []).append(_version(row))
        return grouped


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _document(row: sqlite3.Row, versions: list[Version]) -> Document:
    stats = DocumentStats(**json.loads(row["stats"])) if row["stats"] else None
    return Document(
        id=row["id"],
        title=row["title"],
        authors=row["authors"],
        filename=row["filename"],
        format=row["format"],
        pages=row["pages"],
        size=row["size"],
        sha256=row["sha256"],
        added_at=row["added_at"],
        opened_at=row["opened_at"],
        last_page=row["last_page"],
        favorite=bool(row["favorite"]),
        stats=stats,
        versions=versions,
    )


def _version(row: sqlite3.Row) -> Version:
    return Version(
        id=row["id"],
        document_id=row["document_id"],
        target_lang=row["target_lang"],
        engine=row["engine"],
        pages=json.loads(row["pages"]) if row["pages"] else None,
        created_at=row["created_at"],
        report=json.loads(row["report"]),
    )
