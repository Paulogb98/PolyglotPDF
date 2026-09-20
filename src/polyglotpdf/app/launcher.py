"""Starts the reader: the in-process server and the desktop window over it.

The server is an implementation detail of the desktop application: it binds a loopback
port (a free one by default), requires a token that only the window receives, and stops
when the window closes. ``headless`` runs the server alone — for developing the
interface with Vite's hot reload, and for tests — and prints the address to open.
"""

from __future__ import annotations

import logging
import socket
import sys
import threading
import time
from collections.abc import Callable
from typing import Any, cast

from .config import LOOPBACK_HOSTS, AppConfig

log = logging.getLogger(__name__)


def run(
    config: AppConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    headless: bool = False,
    on_ready: Callable[[Any], None] | None = None,
) -> int:
    import uvicorn

    from .server import create_app
    from .state import AppState

    if host not in LOOPBACK_HOSTS:
        log.warning("Serving on %s: anyone on the network with the token can use the library", host)
        config.allowed_hosts = config.allowed_hosts | {host.lower(), socket.gethostname().lower()}
    if not headless:
        _require_webview()
    sock = _bind(host, port)
    actual_port = sock.getsockname()[1]
    app = create_app(config)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        print("The server did not start.", file=sys.stderr)
        return 1

    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{actual_port}/?token={config.token}"
    try:
        if headless:
            print(f"PolyglotPDF (headless): {url}")
            print("Press Ctrl+C to stop.")
            while thread.is_alive():
                thread.join(0.5)
        else:
            from .desktop import open_window

            open_window(url, cast(AppState, app.state.polyglotpdf), on_ready)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    return 0


def _require_webview() -> None:
    try:
        import webview  # noqa: F401
    except ImportError as exc:
        from ..errors import ConfigError

        raise ConfigError(
            "The app needs the native window (pywebview): "
            "uv sync --extra app (or pip install 'polyglotpdf[app]')"
        ) from exc


def _bind(host: str, port: int) -> socket.socket:
    """Bind the requested port, or any free port when it is taken (or when it is 0)."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.bind((host, 0))
    sock.listen(64)
    return sock
