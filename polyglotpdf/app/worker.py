"""Body of a translation or estimation job.

Jobs normally run in a child process: PyMuPDF must not be used from two threads at
once, and a long translation would otherwise compete with the reader for it (and
for the GIL). Events go back to the parent through a queue as ``(kind, data)``
tuples: ``progress``, then one of ``done``, ``cancelled`` or ``error``.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from ..config import Settings
from ..errors import Cancelled, PolyglotPDFError
from ..pipeline import PdfTranslator
from ..progress import FunctionProgress


class EventSink(Protocol):
    def put(self, item: tuple[str, Any]) -> None: ...


def run_job(kind: str, payload: dict[str, Any], events: EventSink, cancel: Any) -> None:
    """Run a ``translate`` or ``estimate`` job described by ``payload``.

    ``payload``: ``settings`` (``Settings.to_dict()``), ``api_key``, ``input`` and, to
    translate, ``output``. ``cancel`` is a threading or multiprocessing event.
    """
    logging.basicConfig(level=logging.WARNING)
    try:
        settings = Settings.from_dict(payload["settings"])
        settings.translation.api_key = payload.get("api_key")

        def report(stage: str, done: int, total: int) -> None:
            events.put(("progress", {"stage": stage, "done": done, "total": total}))

        translator = PdfTranslator(settings, progress=FunctionProgress(report))
        if kind == "estimate":
            result = translator.estimate(payload["input"]).to_dict()
        elif kind == "translate":
            result = translator.translate(
                payload["input"], payload["output"], cancel=cancel
            ).to_dict()
        else:
            raise ValueError(f"Unknown job kind {kind!r}")
        events.put(("done", result))
    except Cancelled:
        events.put(("cancelled", None))
    except PolyglotPDFError as exc:
        events.put(("error", {"type": type(exc).__name__, "message": str(exc)}))
    except Exception as exc:  # reported to the interface instead of killing the process
        events.put(("error", {"type": type(exc).__name__, "message": repr(exc)}))
