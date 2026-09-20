"""Catalogue of translation engines: what each one is, what it needs and its defaults.

Applications (a GUI, a web service) use :func:`list_engines` to build their engine
picker: the ``kind`` separates the free standard translation from the AI services,
``key_env``/``requires_key`` tell whether to ask for an API key and
``lists_models`` whether :func:`polyglotpdf.translation.registry.list_models` can
fetch the provider's current models. ``supports_chat`` marks the engines the
reading companion can talk to (:func:`chat_engines`).

Model names change every few months: the defaults below are only starting points
(checked against the providers' documentation in September 2026).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from ..errors import ConfigError


class EngineKind(StrEnum):
    STANDARD = "standard"  # free machine translation, no key (the default)
    AI = "ai"  # AI services (language models, neural MT) used with the user's API key
    OFFLINE = "offline"  # local test engines, no network


@dataclass(frozen=True, slots=True)
class EngineInfo:
    name: str
    label: str
    kind: EngineKind
    description: str
    key_env: tuple[str, ...] = ()
    requires_key: bool = False
    default_model: str | None = None
    base_url: str | None = None
    lists_models: bool = False
    supports_glossary: bool = False
    supports_chat: bool = False
    website: str = ""

    def api_key(self, explicit: str | None = None) -> str | None:
        """The explicit key, or the first configured environment variable."""
        if explicit:
            return explicit
        for variable in self.key_env:
            value = os.environ.get(variable)
            if value:
                return value
        return None

    @property
    def has_key(self) -> bool:
        return self.api_key() is not None


_ENGINES = (
    EngineInfo(
        name="google",
        label="Google Translate",
        kind=EngineKind.STANDARD,
        description="Free translation through Google’s web endpoint, no API key.",
        website="https://translate.google.com",
    ),
    EngineInfo(
        name="deepl",
        label="DeepL",
        kind=EngineKind.AI,
        description="DeepL neural translation (Free and Pro plans).",
        key_env=("DEEPL_AUTH_KEY", "DEEPL_API_KEY"),
        requires_key=True,
        website="https://www.deepl.com/pro-api",
    ),
    EngineInfo(
        name="anthropic",
        label="Anthropic Claude",
        kind=EngineKind.AI,
        description="Claude models, with structured output and prompt caching.",
        key_env=("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
        requires_key=True,
        default_model="claude-opus-5",
        lists_models=True,
        supports_glossary=True,
        supports_chat=True,
        website="https://console.anthropic.com",
    ),
    EngineInfo(
        name="openai",
        label="OpenAI",
        kind=EngineKind.AI,
        description="GPT models through the Responses API.",
        key_env=("OPENAI_API_KEY",),
        requires_key=True,
        default_model="gpt-5.6-terra",
        lists_models=True,
        supports_glossary=True,
        supports_chat=True,
        website="https://platform.openai.com",
    ),
    EngineInfo(
        name="deepseek",
        label="DeepSeek",
        kind=EngineKind.AI,
        description="DeepSeek models (OpenAI-compatible API).",
        key_env=("DEEPSEEK_API_KEY",),
        requires_key=True,
        default_model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        lists_models=True,
        supports_glossary=True,
        supports_chat=True,
        website="https://platform.deepseek.com",
    ),
    EngineInfo(
        name="gemini",
        label="Google Gemini",
        kind=EngineKind.AI,
        description="Gemini models through the OpenAI-compatible endpoint.",
        key_env=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        requires_key=True,
        default_model="gemini-3.8-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        lists_models=True,
        supports_glossary=True,
        supports_chat=True,
        website="https://aistudio.google.com",
    ),
    EngineInfo(
        name="mistral",
        label="Mistral AI",
        kind=EngineKind.AI,
        description="Mistral models (OpenAI-compatible API).",
        key_env=("MISTRAL_API_KEY",),
        requires_key=True,
        default_model="mistral-medium-latest",
        base_url="https://api.mistral.ai/v1",
        lists_models=True,
        supports_glossary=True,
        supports_chat=True,
        website="https://console.mistral.ai",
    ),
    EngineInfo(
        name="xai",
        label="xAI Grok",
        kind=EngineKind.AI,
        description="Grok models (OpenAI-compatible API).",
        key_env=("XAI_API_KEY",),
        requires_key=True,
        default_model="grok-4.6",
        base_url="https://api.x.ai/v1",
        lists_models=True,
        supports_glossary=True,
        supports_chat=True,
        website="https://console.x.ai",
    ),
    EngineInfo(
        name="qwen",
        label="Alibaba Qwen",
        kind=EngineKind.AI,
        description="Qwen models through Model Studio (OpenAI-compatible mode).",
        key_env=("DASHSCOPE_API_KEY",),
        requires_key=True,
        default_model="qwen-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        lists_models=True,
        supports_glossary=True,
        supports_chat=True,
        website="https://www.alibabacloud.com/product/modelstudio",
    ),
    EngineInfo(
        name="openrouter",
        label="OpenRouter",
        kind=EngineKind.AI,
        description="Hundreds of models from many providers with a single key.",
        key_env=("OPENROUTER_API_KEY",),
        requires_key=True,
        default_model="google/gemini-3.7-flash",
        base_url="https://openrouter.ai/api/v1",
        lists_models=True,
        supports_glossary=True,
        supports_chat=True,
        website="https://openrouter.ai",
    ),
    EngineInfo(
        name="ollama",
        label="Ollama (local)",
        kind=EngineKind.AI,
        description="Open models running on your own computer, no key.",
        default_model="qwen3",
        base_url="http://localhost:11434/v1",
        lists_models=True,
        supports_glossary=True,
        supports_chat=True,
        website="https://ollama.com",
    ),
    EngineInfo(
        name="openai-compatible",
        label="Another OpenAI-compatible provider",
        kind=EngineKind.AI,
        description="Any Chat Completions server: give its base_url, model and key.",
        lists_models=True,
        supports_glossary=True,
        supports_chat=True,
    ),
    EngineInfo(
        name="pseudo",
        label="Pseudo-translation",
        kind=EngineKind.OFFLINE,
        description="Accents and stretches the text (~30%) to test the layout at no cost.",
    ),
    EngineInfo(
        name="echo",
        label="Echo",
        kind=EngineKind.OFFLINE,
        description=(
            "Offline tests: translating rebuilds the original text; the reading companion "
            "shows the context it would send to the AI."
        ),
        supports_chat=True,
    ),
)

ENGINES: dict[str, EngineInfo] = {engine.name: engine for engine in _ENGINES}
ALIASES = {"claude": "anthropic", "grok": "xai", "chatgpt": "openai", "custom": "openai-compatible"}


def list_engines(kind: EngineKind | None = None) -> list[EngineInfo]:
    return [engine for engine in _ENGINES if kind is None or engine.kind is kind]


def chat_engines() -> list[EngineInfo]:
    """Engines that can hold a conversation (used by the reading companion)."""
    return [engine for engine in _ENGINES if engine.supports_chat]


def get_engine(name: str) -> EngineInfo:
    key = name.strip().lower()
    key = ALIASES.get(key, key)
    try:
        return ENGINES[key]
    except KeyError:
        raise ConfigError(f"Unknown engine {name!r}; choose one of: {', '.join(ENGINES)}") from None


def engine_names() -> list[str]:
    """Every accepted engine name, aliases included (for command-line choices)."""
    return [*ENGINES, *ALIASES]
