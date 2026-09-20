"""User preferences of the reader application (no secrets: keys live in the credential store)."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from ..config import EFFORT_LEVELS
from ..errors import ConfigError
from ..reading.context import CONTEXT_SIZES
from ..translation.engines import get_engine
from ..translation.languages import canonical

PAPERS = ("cream", "white", "sepia", "night")
COLUMN_WIDTHS = ("narrow", "book", "wide")
ADVANCE_MODES = ("pages", "scroll")
OPEN_MODES = ("ask", "tutor", "read", "remember")
HIGHLIGHT_COLORS = ("amarelo", "verde", "coral", "azul")
#: "auto" follows the system's language (the interface resolves it).
INTERFACE_LANGUAGES = ("auto", "pt-BR", "en")


@dataclass(slots=True)
class EnginePrefs:
    model: str | None = None  # None: the engine's default model
    base_url: str | None = None  # None: the engine's default endpoint


@dataclass(slots=True)
class ReadingPrefs:
    """The reader's own settings: the text, the paper and the movement."""

    text_size: float = 14.5  # px of the text layer; the page image never changes
    column_width: str = "book"
    paper: str = "cream"
    page_animation: bool = True
    reduce_motion: bool = False
    advance: str = "pages"
    highlight_color: str = "amarelo"
    save_to_notebook: bool = True
    card_on_highlight: bool = False
    explain_on_highlight: bool = False
    open_mode: str = "ask"
    companion_enabled: bool = True
    tutor_enabled: bool = True

    def validate(self) -> ReadingPrefs:
        self.text_size = round(min(18.0, max(12.0, float(self.text_size))), 1)
        _one_of("column_width", self.column_width, COLUMN_WIDTHS)
        _one_of("paper", self.paper, PAPERS)
        _one_of("advance", self.advance, ADVANCE_MODES)
        _one_of("open_mode", self.open_mode, OPEN_MODES)
        _one_of("highlight_color", self.highlight_color, HIGHLIGHT_COLORS)
        return self


def _one_of(name: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ConfigError(f"Unknown {name} {value!r}; choose one of {', '.join(allowed)}")


@dataclass(slots=True)
class Preferences:
    translation_engine: str = "google"
    source_lang: str = "auto"
    target_lang: str = "pt-BR"
    #: None: the first AI engine with a key (see the application state).
    companion_engine: str | None = None
    companion_language: str = "pt-BR"
    interface_language: str = "auto"
    companion_effort: str = "medium"
    context_size: str = "medium"
    reading: ReadingPrefs = field(default_factory=ReadingPrefs)
    engines: dict[str, EnginePrefs] = field(default_factory=dict)

    def engine(self, name: str) -> EnginePrefs:
        return self.engines.get(get_engine(name).name, EnginePrefs())

    def validate(self) -> Preferences:
        self.translation_engine = get_engine(self.translation_engine).name
        if self.companion_engine:
            info = get_engine(self.companion_engine)
            if not info.supports_chat:
                raise ConfigError(f"{info.label} cannot be used by the reading companion")
            self.companion_engine = info.name
        if self.companion_effort not in EFFORT_LEVELS:
            raise ConfigError(f"Unknown effort {self.companion_effort!r}")
        if self.context_size not in CONTEXT_SIZES:
            raise ConfigError(f"Unknown context size {self.context_size!r}")
        self.source_lang = "auto" if self.source_lang == "auto" else canonical(self.source_lang)
        self.target_lang = canonical(self.target_lang)
        self.companion_language = canonical(self.companion_language)
        _one_of("interface_language", self.interface_language, INTERFACE_LANGUAGES)
        self.reading = self.reading.validate()
        self.engines = {get_engine(name).name: value for name, value in self.engines.items()}
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Preferences:
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"Unknown preferences: {', '.join(sorted(unknown))}")
        values = dict(data)
        engines = values.pop("engines", None) or {}
        reading = values.pop("reading", None) or {}
        prefs = cls(**values)
        prefs.reading = _reading_prefs(reading)
        prefs.engines = {name: _engine_prefs(value) for name, value in engines.items()}
        return prefs.validate()


def _reading_prefs(value: Mapping[str, Any]) -> ReadingPrefs:
    known = {f.name for f in fields(ReadingPrefs)}
    unknown = set(value) - known
    if unknown:
        raise ConfigError(f"Unknown reading preferences: {', '.join(sorted(unknown))}")
    return ReadingPrefs(**dict(value))


def _engine_prefs(value: Mapping[str, Any]) -> EnginePrefs:
    unknown = set(value) - {"model", "base_url"}
    if unknown:
        raise ConfigError(f"Unknown engine preferences: {', '.join(sorted(unknown))}")
    model = (value.get("model") or "").strip() or None
    base_url = (value.get("base_url") or "").strip() or None
    return EnginePrefs(model=model, base_url=base_url)


class PreferencesStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._prefs = self._load()

    def get(self) -> Preferences:
        with self._lock:
            return Preferences.from_dict(self._prefs.to_dict())

    def update(self, changes: Mapping[str, Any]) -> Preferences:
        """Apply partial changes (engine entries are merged per engine) and save."""
        with self._lock:
            data = self._prefs.to_dict()
            engines = dict(data["engines"])
            for name, value in dict(changes.get("engines") or {}).items():
                key = get_engine(name).name
                engines[key] = {**engines.get(key, {}), **dict(value)}
            reading = {**data["reading"], **dict(changes.get("reading") or {})}
            data.update({k: v for k, v in changes.items() if k not in {"engines", "reading"}})
            data["engines"] = engines
            data["reading"] = reading
            prefs = Preferences.from_dict(data)
            self._save(prefs)
            self._prefs = prefs
            return replace(prefs)

    def _load(self) -> Preferences:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return Preferences.from_dict(data)
        except FileNotFoundError:
            return Preferences()
        except (json.JSONDecodeError, ConfigError, TypeError) as exc:
            broken = self.path.with_suffix(".invalid.json")
            self.path.replace(broken)
            raise ConfigError(f"Invalid preferences file moved to {broken}: {exc}") from exc

    def _save(self, prefs: Preferences) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(prefs.to_dict(), indent=2), encoding="utf-8")
        temporary.replace(self.path)
