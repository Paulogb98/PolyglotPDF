"""Engine catalogue and construction (no network)."""

import pytest

from polyglotpdf.config import TranslationSettings
from polyglotpdf.errors import ConfigError
from polyglotpdf.translation.anthropic_api import AnthropicTranslator
from polyglotpdf.translation.engines import EngineKind, get_engine, list_engines
from polyglotpdf.translation.google import GoogleTranslator
from polyglotpdf.translation.openai_api import ChatCompletionsTranslator, OpenAITranslator
from polyglotpdf.translation.registry import check_engine, create_translator, list_models

AI_ENGINES = {
    "deepl",
    "anthropic",
    "openai",
    "deepseek",
    "gemini",
    "mistral",
    "xai",
    "qwen",
    "openrouter",
    "ollama",
    "openai-compatible",
}


def test_catalogue_separates_standard_ai_and_offline_engines() -> None:
    assert [e.name for e in list_engines(EngineKind.STANDARD)] == ["google"]
    assert {e.name for e in list_engines(EngineKind.AI)} == AI_ENGINES
    assert {e.name for e in list_engines(EngineKind.OFFLINE)} == {"pseudo", "echo"}


def test_aliases_and_unknown_names() -> None:
    assert get_engine("claude").name == "anthropic"
    assert get_engine(" GROK ").name == "xai"
    with pytest.raises(ConfigError):
        get_engine("babelfish")


def test_api_key_comes_from_settings_or_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    info = get_engine("deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert info.api_key() is None and not info.has_key
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
    assert info.api_key() == "from-env"
    assert info.api_key("explicit") == "explicit"


def test_google_is_the_default_engine() -> None:
    assert isinstance(create_translator(TranslationSettings()), GoogleTranslator)


@pytest.mark.parametrize(
    ("engine", "url_part", "json_mode"),
    [
        ("deepseek", "api.deepseek.com", "object"),
        ("gemini", "generativelanguage.googleapis.com", "schema"),
        ("mistral", "api.mistral.ai", "object"),
        ("xai", "api.x.ai", "schema"),
        ("qwen", "dashscope", "object"),
        ("openrouter", "openrouter.ai", "object"),
    ],
)
def test_compatible_providers(engine: str, url_part: str, json_mode: str) -> None:
    translator = create_translator(TranslationSettings(engine=engine, api_key="key"))
    assert isinstance(translator, ChatCompletionsTranslator)
    assert url_part in str(translator._client.base_url)
    assert translator.json_mode == json_mode
    assert translator.model == get_engine(engine).default_model


def test_local_ollama_needs_no_key_and_runs_sequentially() -> None:
    translator = create_translator(TranslationSettings(engine="ollama"))
    assert isinstance(translator, ChatCompletionsTranslator)
    assert translator.max_concurrency == 1


def test_openai_and_anthropic_use_their_own_apis() -> None:
    assert isinstance(
        create_translator(TranslationSettings(engine="openai", api_key="sk-test")), OpenAITranslator
    )
    anthropic = create_translator(
        TranslationSettings(engine="anthropic", api_key="sk-ant-test", model="claude-sonnet-5")
    )
    assert isinstance(anthropic, AnthropicTranslator) and anthropic.model == "claude-sonnet-5"


def test_missing_key_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        create_translator(TranslationSettings(engine="openai"))


def test_custom_provider_needs_a_model_and_an_endpoint() -> None:
    with pytest.raises(ConfigError):
        create_translator(TranslationSettings(engine="openai-compatible"))
    with pytest.raises(ConfigError):
        create_translator(TranslationSettings(engine="openai-compatible", model="m"))
    translator = create_translator(
        TranslationSettings(engine="custom", model="m", base_url="http://localhost:8000/v1")
    )
    assert isinstance(translator, ChatCompletionsTranslator)


def test_checks_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    assert check_engine("google").ok and check_engine("pseudo").ok
    assert not check_engine("babelfish").ok
    monkeypatch.delenv("DEEPL_AUTH_KEY", raising=False)
    monkeypatch.delenv("DEEPL_API_KEY", raising=False)
    assert not check_engine("deepl").ok
    assert list_models("google") == [] and list_models("deepl") == []
