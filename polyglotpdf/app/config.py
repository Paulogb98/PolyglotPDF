"""Configuration of the reader application."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

#: Host names accepted in the Host header (protection against DNS rebinding).
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
STATIC_DIR = Path(__file__).resolve().parent / "static"


def default_data_dir() -> Path:
    """Where the library, its database and the preferences live."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "polyglotpdf" / "app"
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "polyglotpdf"


def new_token() -> str:
    """The access token: ``POLYGLOTPDF_APP_TOKEN`` when set (development), else a new one."""
    return os.environ.get("POLYGLOTPDF_APP_TOKEN", "").strip() or secrets.token_urlsafe(24)


@dataclass(slots=True)
class AppConfig:
    data_dir: Path = field(default_factory=default_data_dir)
    #: Access token: the interface must present it (cookie set from ``/?token=...``).
    token: str = field(default_factory=new_token)
    allowed_hosts: frozenset[str] = LOOPBACK_HOSTS
    static_dir: Path = STATIC_DIR
    #: "process": jobs run in a child process (PyMuPDF is not thread-safe); "thread"
    #: runs them in a worker thread (tests).
    job_isolation: str = "process"
    #: Delay between the pieces streamed by the offline "echo" companion (demos).
    echo_delay: float = 0.01

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.static_dir = Path(self.static_dir)
        if self.job_isolation not in ("process", "thread"):
            raise ValueError("job_isolation must be 'process' or 'thread'")
