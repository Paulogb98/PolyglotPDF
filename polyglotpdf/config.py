"""Runtime settings.

Settings can be built programmatically, loaded from a TOML file or from a mapping
(for instance JSON coming from a user interface) and overridden by command-line
options. Every field has a default, so an empty configuration is valid.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any

from .errors import ConfigError

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
SECRET_MASK = "********"


@dataclass(slots=True)
class TranslationSettings:
    engine: str = "google"  # see polyglotpdf.translation.engines.list_engines()
    source_lang: str = "auto"
    target_lang: str = "pt-BR"
    model: str | None = None  # None: the engine's default model
    api_key: str | None = None  # None: the engine's environment variable
    base_url: str | None = None  # None: the engine's default endpoint
    temperature: float | None = None  # None: the provider's default
    # Claude only. Translation is a high-volume, well-specified task: "medium" keeps
    # quality while avoiding unnecessary thinking cost.
    effort: str = "medium"
    concurrency: int = 4
    batch_max_items: int = 40
    batch_max_chars: int = 7000
    request_timeout: float = 600.0
    max_retries: int = 4
    use_cache: bool = True
    cache_path: Path | None = None
    glossary_path: Path | None = None


@dataclass(slots=True)
class ContentSettings:
    """What is sent for translation besides prose (formulas are never translated)."""

    translate_code: bool = False  # multi-line monospaced listings


@dataclass(slots=True)
class LayoutSettings:
    min_font_scale: float = 0.72  # preferred lower bound when shrinking text to fit
    hard_min_font_scale: float = 0.5  # absolute lower bound; below it the text overflows
    expand_into_free_space: bool = True
    hyphenate: bool = True


@dataclass(slots=True)
class FontSettings:
    """Fonts for the translated text: built-in names (tiro, helv, cour, cjk...) or font files."""

    serif: str | None = None
    serif_bold: str | None = None
    serif_italic: str | None = None
    serif_bold_italic: str | None = None
    sans: str | None = None
    sans_bold: str | None = None
    sans_italic: str | None = None
    sans_bold_italic: str | None = None
    mono: str | None = None
    mono_bold: str | None = None
    fallback: str | None = None  # used for glyphs missing from the main fonts


@dataclass(slots=True)
class OutputSettings:
    bilingual: bool = False
    subset_fonts: bool = True
    # With a page selection, keep the other pages (untranslated) instead of dropping
    # them, so the output lines up page by page with the original.
    keep_all_pages: bool = False


@dataclass(slots=True)
class Settings:
    translation: TranslationSettings = field(default_factory=TranslationSettings)
    content: ContentSettings = field(default_factory=ContentSettings)
    layout: LayoutSettings = field(default_factory=LayoutSettings)
    fonts: FontSettings = field(default_factory=FontSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    pages: str | None = None  # e.g. "1-3,7"; None = whole document

    def validate(self) -> Settings:
        # Imported here: the translation package imports this module.
        from .translation.engines import get_engine

        t, lay = self.translation, self.layout
        get_engine(t.engine)
        if t.effort not in EFFORT_LEVELS:
            raise ConfigError(
                f"Unknown effort {t.effort!r}; choose one of {', '.join(EFFORT_LEVELS)}"
            )
        if t.concurrency < 1 or t.batch_max_items < 1 or t.batch_max_chars < 200:
            raise ConfigError("concurrency, batch_max_items and batch_max_chars must be positive")
        if t.temperature is not None and not 0.0 <= t.temperature <= 2.0:
            raise ConfigError("temperature must be between 0 and 2")
        if not 0.2 <= lay.hard_min_font_scale <= lay.min_font_scale <= 1.0:
            raise ConfigError("Expected 0.2 <= hard_min_font_scale <= min_font_scale <= 1.0")
        if t.glossary_path is not None and not Path(t.glossary_path).is_file():
            raise ConfigError(f"Glossary file not found: {t.glossary_path}")
        return self

    def to_dict(self, *, include_secrets: bool = False) -> dict[str, Any]:
        """Plain JSON-compatible data; the API key is masked unless ``include_secrets``."""
        data: dict[str, Any] = _plain(asdict(self))
        if data["translation"]["api_key"] and not include_secrets:
            data["translation"]["api_key"] = SECRET_MASK
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Settings:
        settings: Settings = _from_mapping(cls, dict(data), context="settings")
        if settings.translation.api_key == SECRET_MASK:
            settings.translation.api_key = None
        return settings

    @classmethod
    def from_toml(cls, path: str | os.PathLike[str]) -> Settings:
        file = Path(path)
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"Configuration file not found: {file}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Invalid TOML in {file}: {exc}") from exc
        settings: Settings = _from_mapping(cls, data, context=str(file))
        # Relative paths inside the config file are relative to the file itself.
        for name in ("cache_path", "glossary_path"):
            value = getattr(settings.translation, name)
            if value is not None and not Path(value).is_absolute():
                setattr(settings.translation, name, (file.parent / value).resolve())
        return settings


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _from_mapping(cls: type[Any], data: dict[str, Any], *, context: str) -> Any:
    known = {f.name: f for f in fields(cls)}
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if key not in known:
            raise ConfigError(f"Unknown setting {key!r} in {context}")
        factory = known[key].default_factory
        default = factory() if callable(factory) else None
        if is_dataclass(default):
            if not isinstance(value, Mapping):
                raise ConfigError(f"Setting {key!r} in {context} must be a table")
            kwargs[key] = _from_mapping(type(default), dict(value), context=f"{context}:{key}")
        elif key.endswith("_path") and value is not None:
            kwargs[key] = Path(value)
        else:
            kwargs[key] = value
    return cls(**kwargs)


def with_overrides(settings: Settings, **sections: dict[str, Any]) -> Settings:
    """Return a copy of ``settings`` with non-None values from ``sections`` applied."""
    updated = settings
    for section_name, values in sections.items():
        clean = {k: v for k, v in values.items() if v is not None}
        if section_name == "root":
            updated = replace(updated, **clean)
        elif clean:
            section = getattr(updated, section_name)
            updated = replace(updated, **{section_name: replace(section, **clean)})
    return updated


def default_cache_path() -> Path:
    """Platform-appropriate location for the translation cache."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "polyglotpdf" / "translations.sqlite3"
