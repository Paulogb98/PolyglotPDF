"""Documents open in the reader, reused between requests."""

from __future__ import annotations

import threading
from collections import OrderedDict

from ..reading.index import DocumentIndex
from .library import Library

Key = tuple[str, str | None]  # (document id, translation id or None for the original)


class DocumentRegistry:
    """Keeps the most recently used :class:`DocumentIndex` objects open (LRU)."""

    def __init__(self, library: Library, capacity: int = 8) -> None:
        self.library = library
        self.capacity = max(1, capacity)
        self._open: OrderedDict[Key, DocumentIndex] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, document_id: str, version_id: str | None = None) -> DocumentIndex:
        key: Key = (document_id, version_id)
        with self._lock:
            index = self._open.get(key)
            if index is not None:
                self._open.move_to_end(key)
                return index
        document = self.library.get(document_id)
        path = self.library.reading_path(document_id, version_id)
        stats = document.stats if version_id is None else None
        index = DocumentIndex.open(path, name=document.title, stats=stats)
        if version_id is None and document.stats is None:
            self.library.save_stats(document_id, index.stats)
        evicted: list[DocumentIndex] = []
        with self._lock:
            current = self._open.get(key)
            if current is not None:  # opened meanwhile by another request
                evicted.append(index)
                index = current
            else:
                self._open[key] = index
            while len(self._open) > self.capacity:
                evicted.append(self._open.popitem(last=False)[1])
        for item in evicted:
            item.close()
        return index

    def close(
        self, document_id: str, version_id: str | None = None, *, all_versions: bool = True
    ) -> None:
        """Close a document (by default with all its translations) before deleting files."""
        with self._lock:
            keys = [
                key
                for key in self._open
                if key[0] == document_id and (all_versions or key[1] == version_id)
            ]
            closing = [self._open.pop(key) for key in keys]
        for index in closing:
            index.close()

    def close_all(self) -> None:
        with self._lock:
            closing = list(self._open.values())
            self._open.clear()
        for index in closing:
            index.close()
