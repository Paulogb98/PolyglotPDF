"""Progress reporting, decoupled from any user-interface library."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol

STAGES = ("analyze", "translate", "render")


class ProgressReporter(Protocol):
    """Receives progress events for the pipeline stages ``analyze``, ``translate`` and ``render``.

    ``advance`` may be called from worker threads.
    """

    def start(self, stage: str, total: int) -> None: ...

    def advance(self, stage: str, amount: int = 1) -> None: ...

    def finish(self, stage: str) -> None: ...


class NullProgress:
    def start(self, stage: str, total: int) -> None:
        pass

    def advance(self, stage: str, amount: int = 1) -> None:
        pass

    def finish(self, stage: str) -> None:
        pass


class FunctionProgress:
    """Calls ``callback(stage, done, total)`` on every change (convenient for GUIs).

    The callback may run on a worker thread: GUI toolkits must hand the update over
    to their own UI thread.
    """

    def __init__(self, callback: Callable[[str, int, int], None]) -> None:
        self._callback = callback
        self._state: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()

    def start(self, stage: str, total: int) -> None:
        with self._lock:
            self._state[stage] = (0, total)
        self._callback(stage, 0, total)

    def advance(self, stage: str, amount: int = 1) -> None:
        with self._lock:
            done, total = self._state.get(stage, (0, 0))
            done += amount
            self._state[stage] = (done, total)
        self._callback(stage, done, total)

    def finish(self, stage: str) -> None:
        with self._lock:
            _, total = self._state.get(stage, (0, 0))
            self._state[stage] = (total, total)
        self._callback(stage, total, total)
