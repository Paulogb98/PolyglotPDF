"""The desktop application: one native window over an in-process server.

The interface is the same React build the server hands out, but it lives in a native
window (pywebview: WebView2 on Windows, WebKit on macOS, GTK/Qt on Linux) with no
browser around it — no address bar, no tabs, no browser menus or shortcuts. The server
listens on a random loopback port with a fresh token that only the window knows.

What a browser cannot do, the window does through :class:`Bridge`, exposed to the page
as ``window.pywebview.api``: native dialogs to pick books and to save exports, importing
files straight from disk (no upload), and opening the data folder in the file manager.
The window remembers its size and position between runs.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import AppConfig, default_data_dir, new_token
from .library import SUPPORTED

if TYPE_CHECKING:
    from .state import AppState

log = logging.getLogger(__name__)

TITLE = "PolyglotPDF"
#: Taskbar identity on Windows (``Company.Product``), so the window is not grouped
#: under — and drawn with the icon of — the Python interpreter running it.
APP_ID = "PolyglotPDF.Reader"
ICON = Path(__file__).resolve().parent / "assets" / "icon.ico"
DEFAULT_SIZE = (1440, 920)
MIN_SIZE = (1024, 680)


class Bridge:
    """Native abilities for the page (``window.pywebview.api``).

    pywebview publishes every public method; private attributes stay on this side. Each
    call runs in its own thread, so a long import does not freeze the window.
    """

    def __init__(self, state: AppState) -> None:
        self._state = state
        self._window: Any = None

    def attach(self, window: Any) -> None:
        self._window = window

    # ------------------------------------------------------------------ books
    def choose_books(self) -> list[str]:
        """The open dialog, filtered to the formats the library accepts."""
        import webview

        patterns = ";".join(f"*{suffix}" for suffix in sorted(SUPPORTED))
        chosen = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=True,
            file_types=(f"Books ({patterns})", "All files (*.*)"),
        )
        return [str(path) for path in chosen or ()]

    def import_books(self, paths: list[str]) -> list[dict[str, Any]]:
        """Import files straight from disk; one result per path, errors included."""
        results: list[dict[str, Any]] = []
        for raw in paths:
            path = Path(raw)
            try:
                document, created = self._state.library.add(path, path.name)
                results.append({"path": raw, "document": document.to_dict(), "created": created})
            except Exception as exc:  # the page shows it next to the file
                log.warning("Import of %s failed: %s", path, exc)
                results.append({"path": raw, "error": str(exc) or type(exc).__name__})
        return results

    # ------------------------------------------------------------------ saving
    def save_text(self, suggested: str, text: str) -> str | None:
        """Save a text export (the notebook as Markdown, cards as CSV) where the reader says."""
        target = self._save_dialog(suggested)
        if target is None:
            return None
        target.write_text(text, encoding="utf-8")
        return str(target)

    def export_document(self, document_id: str, version_id: str | None = None) -> str | None:
        """Save a copy of the book — the original, or one of its translations."""
        library = self._state.library
        document = library.get(document_id)
        if version_id:
            translation = library.version(document_id, version_id)
            source = library.reading_path(document_id, version_id)
            suggested = f"{Path(document.filename).stem}.{translation.target_lang}.pdf"
        else:
            source = library.source_path(document_id)
            suggested = document.filename
        target = self._save_dialog(suggested)
        if target is None:
            return None
        shutil.copyfile(source, target)
        return str(target)

    def _save_dialog(self, suggested: str) -> Path | None:
        import webview

        chosen = self._window.create_file_dialog(
            webview.FileDialog.SAVE, save_filename=Path(suggested).name
        )
        if not chosen:
            return None
        return Path(chosen if isinstance(chosen, str) else chosen[0])

    # ------------------------------------------------------------------ the rest
    def reveal_data(self) -> None:
        """Open the library folder in the system's file manager."""
        folder = self._state.config.data_dir
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def platform(self) -> dict[str, Any]:
        return {"desktop": True, "os": sys.platform}


# ---------------------------------------------------------------------- window state
def _state_file(data_dir: Path) -> Path:
    return data_dir / "window.json"


def load_geometry(data_dir: Path) -> dict[str, int]:
    """The size and position the window had when it was last closed."""
    geometry = {"width": DEFAULT_SIZE[0], "height": DEFAULT_SIZE[1]}
    try:
        saved = json.loads(_state_file(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return geometry
    for key in ("width", "height", "x", "y"):
        value = saved.get(key)
        if isinstance(value, int):
            geometry[key] = value
    geometry["width"] = max(MIN_SIZE[0], geometry["width"])
    geometry["height"] = max(MIN_SIZE[1], geometry["height"])
    # A window left on a screen that is no longer there would open out of sight.
    if geometry.get("x", 0) < -100 or geometry.get("y", 0) < -100:
        geometry.pop("x", None)
        geometry.pop("y", None)
    return geometry


def save_geometry(data_dir: Path, window: Any) -> None:
    try:
        geometry = {"width": int(window.width), "height": int(window.height)}
        if window.x is not None and window.y is not None:
            geometry.update(x=int(window.x), y=int(window.y))
        _state_file(data_dir).write_text(json.dumps(geometry), encoding="utf-8")
    except (OSError, TypeError, ValueError, AttributeError) as exc:
        log.debug("Could not save the window geometry: %s", exc)


def set_app_id() -> None:
    """Give the process its own taskbar identity (Windows); elsewhere nothing to do."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):  # very old Windows: the Python icon stays
        log.debug("Could not set the taskbar identity", exc_info=True)


def open_window(url: str, state: AppState, on_ready: Callable[[Any], None] | None = None) -> None:
    """Show the interface in a native window; returns when the window is closed.

    ``on_ready`` runs in pywebview's worker thread with the window, once the GUI loop is
    up (the smoke test uses it to inspect the page and close the window).
    """
    import webview

    set_app_id()
    data_dir = state.config.data_dir
    bridge = Bridge(state)
    geometry = load_geometry(data_dir)
    window = webview.create_window(
        TITLE,
        url,
        js_api=bridge,
        width=geometry["width"],
        height=geometry["height"],
        x=geometry.get("x"),
        y=geometry.get("y"),
        min_size=MIN_SIZE,
        background_color="#F5EAD8",  # the paper, so the window never flashes white
        text_select=True,
    )
    if window is None:
        raise RuntimeError("pywebview did not create the window")
    bridge.attach(window)
    window.events.closing += lambda: save_geometry(data_dir, window)
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.start(
        on_ready,
        (window,) if on_ready else None,
        private_mode=False,  # keep the page's own small preferences between runs
        storage_path=str(data_dir / "webview"),
        icon=str(ICON) if ICON.is_file() else None,
        debug=bool(os.environ.get("POLYGLOTPDF_DEVTOOLS")),
    )


def main() -> int:
    """Entry point of ``polyglotpdf-desktop`` (no console on Windows).

    Not named ``PolyglotPDF``: Windows file names ignore case, and ``PolyglotPDF.exe`` would
    replace the ``polyglotpdf.exe`` command line in the same Scripts folder.
    """
    import multiprocessing

    multiprocessing.freeze_support()  # translations run in a child process
    from .launcher import run

    token = os.environ.get("POLYGLOTPDF_APP_TOKEN") or new_token()
    config = AppConfig(data_dir=default_data_dir(), token=token)
    return run(config, port=0)


if __name__ == "__main__":
    raise SystemExit(main())
