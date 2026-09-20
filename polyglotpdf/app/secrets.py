"""API keys of the AI providers.

Keys are kept in the operating system's credential store through ``keyring``
(Windows Credential Manager, macOS Keychain, Secret Service on Linux). Where no
store is available they fall back to a JSON file readable only by the user. Keys
never go to the preferences file, the database, logs or API responses.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Protocol

from .i18n import msg

log = logging.getLogger(__name__)
SERVICE = "polyglotpdf"


class SecretStore(Protocol):
    @property
    def description(self) -> str:
        """Where the keys are kept, for the reader."""
        ...

    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class MemoryStore:
    @property
    def description(self) -> str:
        return msg("secrets.memory")

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def set(self, name: str, value: str) -> None:
        self._values[name] = value

    def delete(self, name: str) -> None:
        self._values.pop(name, None)


class KeyringStore:
    def __init__(self) -> None:
        import keyring

        self._keyring = keyring
        self._backend = type(keyring.get_keyring()).__name__

    @property
    def description(self) -> str:
        """Where the keys are, in the words the reader knows the place by."""
        known = {"WinVaultKeyring": "secrets.windows", "Keyring": "secrets.macos"}
        if self._backend in known and (self._backend != "Keyring" or sys.platform == "darwin"):
            return msg(known[self._backend])
        if "SecretService" in self._backend:
            return msg("secrets.linux")
        return msg("secrets.other", name=self._backend)

    def get(self, name: str) -> str | None:
        value: str | None = self._keyring.get_password(SERVICE, _entry(name))
        return value

    def set(self, name: str, value: str) -> None:
        self._keyring.set_password(SERVICE, _entry(name), value)

    def delete(self, name: str) -> None:
        import keyring.errors

        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            self._keyring.delete_password(SERVICE, _entry(name))


class FileStore:
    @property
    def description(self) -> str:
        return msg("secrets.file")

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def get(self, name: str) -> str | None:
        return self._load().get(name)

    def set(self, name: str, value: str) -> None:
        with self._lock:
            values = self._load()
            values[name] = value
            self._save(values)

    def delete(self, name: str) -> None:
        with self._lock:
            values = self._load()
            if values.pop(name, None) is not None:
                self._save(values)

    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save(self, values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values), encoding="utf-8")
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(self.path)


def default_store(data_dir: Path) -> SecretStore:
    """The system credential store when usable, else a private file in ``data_dir``."""
    try:
        import keyring
        from keyring.backends import fail

        backend = keyring.get_keyring()
        if not isinstance(backend, fail.Keyring) and getattr(backend, "priority", 1) > 0:
            return KeyringStore()
    except Exception as exc:  # keyring missing or broken: use the file
        log.debug("No usable keyring: %s", exc)
    log.warning("No system credential store; API keys are kept in %s", data_dir / "secrets.json")
    return FileStore(data_dir / "secrets.json")


def _entry(name: str) -> str:
    return f"api-key:{name}"
