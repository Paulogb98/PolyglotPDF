"""Engine construction, model listing and credential checks."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..config import TranslationSettings
from ..errors import ConfigError, FatalTranslationError, TranslationError
from .base import Translator
from .engines import EngineInfo, EngineKind, get_engine

log = logging.getLogger(__name__)

#: Chat Completions dialect of each OpenAI-compatible provider.
_CHAT_OPTIONS: dict[str, dict[str, Any]] = {
    "deepseek": {"json_mode": "object"},
    "gemini": {"json_mode": "schema"},
    "mistral": {"json_mode": "object"},
    "xai": {"json_mode": "schema"},
    "qwen": {"json_mode": "object"},
    "openrouter": {"json_mode": "object"},
    "ollama": {"json_mode": "object", "max_concurrency": 1},
    "openai-compatible": {"json_mode": "object"},
}


def create_translator(settings: TranslationSettings) -> Translator:
    info = get_engine(settings.engine)
    key = info.api_key(settings.api_key)
    if info.requires_key and not key and info.name != "anthropic":
        # (Claude may also authenticate with an `ant auth login` profile.)
        variables = " or ".join(info.key_env)
        raise ConfigError(f"{info.label} needs an API key: set api_key or {variables}")
    model = settings.model or info.default_model
    base_url = settings.base_url or info.base_url
    common: dict[str, Any] = {
        "timeout": settings.request_timeout,
        "max_retries": settings.max_retries,
        "max_batch_items": settings.batch_max_items,
        "max_batch_chars": settings.batch_max_chars,
    }

    if info.name == "google":
        from .google import GoogleTranslator

        return GoogleTranslator()
    if info.name == "deepl":
        from .deepl_api import DeepLTranslator

        return DeepLTranslator(key, server_url=settings.base_url)
    if info.name == "echo":
        from .dummy import EchoTranslator

        return EchoTranslator()
    if info.name == "pseudo":
        from .dummy import PseudoTranslator

        return PseudoTranslator()

    if not model:
        raise ConfigError(f"{info.label}: choose a model")
    if info.name == "anthropic":
        from .anthropic_api import AnthropicTranslator

        return AnthropicTranslator(
            model, settings.effort, api_key=key, base_url=settings.base_url, **common
        )
    if info.name == "openai":
        from .openai_api import OpenAITranslator

        return OpenAITranslator(
            model,
            api_key=key,
            base_url=settings.base_url,
            temperature=settings.temperature,
            **common,
        )
    if not base_url:
        raise ConfigError(f"{info.label}: base_url is required")
    from .openai_api import ChatCompletionsTranslator

    return ChatCompletionsTranslator(
        name=info.name,
        label=info.label,
        model=model,
        base_url=base_url,
        api_key=key,
        temperature=settings.temperature,
        **common,
        **_CHAT_OPTIONS.get(info.name, {}),
    )


def list_models(
    engine: str, api_key: str | None = None, base_url: str | None = None, *, timeout: float = 20.0
) -> list[str]:
    """Models currently offered by the provider (needs a valid key). Empty if not supported."""
    info = get_engine(engine)
    if not info.lists_models:
        return []
    key = info.api_key(api_key)
    if info.name == "anthropic":
        import anthropic

        try:
            client = anthropic.Anthropic(
                api_key=key, base_url=base_url, timeout=timeout, max_retries=1
            )
            return sorted(model.id for model in client.models.list())
        except anthropic.AuthenticationError as exc:
            raise FatalTranslationError(f"{info.label}: API key rejected") from exc
        except anthropic.AnthropicError as exc:
            raise TranslationError(f"{info.label}: could not list models ({exc})") from exc

    import openai

    url = base_url or info.base_url
    if info.name != "openai" and not url:
        raise ConfigError(f"{info.label}: base_url is required")
    compatible = openai.OpenAI(
        api_key=key or "not-needed", base_url=url, timeout=timeout, max_retries=1
    )
    try:
        return sorted(model.id for model in compatible.models.list())
    except openai.AuthenticationError as exc:
        raise FatalTranslationError(f"{info.label}: API key rejected") from exc
    except openai.APIError as exc:
        raise TranslationError(f"{info.label}: could not list models ({exc})") from exc


@dataclass(frozen=True, slots=True)
class EngineCheck:
    ok: bool
    message: str
    models: list[str] = field(default_factory=list)


def check_engine(
    engine: str, api_key: str | None = None, base_url: str | None = None
) -> EngineCheck:
    """Validate credentials and connectivity with one cheap request (never translates)."""
    try:
        info = get_engine(engine)
    except ConfigError as exc:
        return EngineCheck(False, str(exc))
    if info.kind is EngineKind.OFFLINE or info.name == "google":
        return EngineCheck(True, "No API key needed")
    if info.name == "deepl":
        return _check_deepl(info, api_key, base_url)
    try:
        models = list_models(info.name, api_key, base_url)
    except (TranslationError, ConfigError) as exc:
        return EngineCheck(False, str(exc))
    return EngineCheck(True, f"{len(models)} model(s) available", models)


def _check_deepl(info: EngineInfo, api_key: str | None, base_url: str | None) -> EngineCheck:
    import deepl

    key = info.api_key(api_key)
    if not key:
        return EngineCheck(False, "DeepL needs an API key (DEEPL_AUTH_KEY)")
    try:
        usage = deepl.Translator(key, server_url=base_url).get_usage()
    except deepl.AuthorizationException:
        return EngineCheck(False, "DeepL: API key rejected")
    except deepl.DeepLException as exc:
        return EngineCheck(False, f"DeepL: {exc}")
    character = usage.character
    if character is not None and character.valid:
        return EngineCheck(True, f"{character.count:,} / {character.limit:,} characters used")
    return EngineCheck(True, "API key accepted")
