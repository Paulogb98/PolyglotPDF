"""User glossary: mandatory translations for specific terms (used by AI engines).

Accepted formats (TOML or JSON)::

    [terms]
    "residual learning" = "aprendizado residual"
    "shortcut connection" = "conexão de atalho"
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ConfigError


@dataclass(frozen=True, slots=True)
class Glossary:
    terms: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.terms

    def fingerprint(self) -> str:
        payload = json.dumps(sorted(self.terms.items()), ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_prompt(self) -> str:
        if not self.terms:
            return ""
        lines = "\n".join(f"- {src} → {dst}" for src, dst in sorted(self.terms.items()))
        return f"Mandatory terminology (source → translation):\n{lines}"

    @classmethod
    def load(cls, path: str | Path) -> Glossary:
        file = Path(path)
        try:
            text = file.read_text(encoding="utf-8")
            data = json.loads(text) if file.suffix.lower() == ".json" else tomllib.loads(text)
        except FileNotFoundError as exc:
            raise ConfigError(f"Glossary not found: {file}") from exc
        except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"Invalid glossary {file}: {exc}") from exc
        unknown = set(data) - {"terms"}
        if unknown:
            raise ConfigError(f"Unknown glossary keys in {file}: {', '.join(sorted(unknown))}")
        terms = data.get("terms", {})
        if not isinstance(terms, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in terms.items()
        ):
            raise ConfigError(f"'terms' in {file} must map strings to strings")
        return cls(terms=dict(terms))
