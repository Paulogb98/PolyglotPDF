from pathlib import Path

import pytest

from polyglotpdf.config import SECRET_MASK, Settings, with_overrides
from polyglotpdf.errors import ConfigError
from polyglotpdf.pdf.loader import parse_page_range
from polyglotpdf.translation.glossary import Glossary
from polyglotpdf.translation.languages import (
    display_name,
    google_code,
    hyphenation_code,
    list_languages,
)


def test_page_ranges() -> None:
    assert parse_page_range("1-3,5", 10) == [0, 1, 2, 4]
    assert parse_page_range("-2", 5) == [0, 1]
    assert parse_page_range("4-", 5) == [3, 4]
    assert parse_page_range(None, 3) == [0, 1, 2]
    for bad in ("0-2", "a", "3-1", "7"):
        with pytest.raises(ConfigError):
            parse_page_range(bad, 5)


def test_settings_from_toml_resolves_relative_paths(tmp_path: Path) -> None:
    (tmp_path / "g.toml").write_text('[terms]\n"deep" = "profundo"\n', encoding="utf-8")
    config = tmp_path / "polyglotpdf.toml"
    config.write_text(
        'pages = "2"\n[translation]\nengine = "deepseek"\ntarget_lang = "es"\n'
        'model = "deepseek-v4-pro"\nglossary_path = "g.toml"\n[layout]\nmin_font_scale = 0.8\n',
        encoding="utf-8",
    )
    settings = Settings.from_toml(config).validate()
    assert settings.pages == "2"
    assert settings.translation.engine == "deepseek" and settings.translation.target_lang == "es"
    assert settings.translation.model == "deepseek-v4-pro"
    assert settings.translation.glossary_path == (tmp_path / "g.toml").resolve()
    assert settings.layout.min_font_scale == 0.8


def test_unknown_settings_and_engines_are_rejected(tmp_path: Path) -> None:
    config = tmp_path / "c.toml"
    config.write_text("[translation]\nmotor = 'x'\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        Settings.from_toml(config)
    with pytest.raises(ConfigError):
        with_overrides(Settings(), translation={"engine": "babelfish"}).validate()


def test_overrides_ignore_none_and_validation_catches_errors() -> None:
    settings = with_overrides(
        Settings(), translation={"engine": "echo", "model": None}, root={"pages": "1"}
    )
    assert settings.translation.engine == "echo" and settings.translation.model is None
    assert settings.pages == "1"
    with pytest.raises(ConfigError):
        with_overrides(Settings(), translation={"effort": "extreme"}).validate()
    with pytest.raises(ConfigError):
        with_overrides(Settings(), translation={"temperature": 5.0}).validate()


def test_dict_round_trip_masks_the_api_key() -> None:
    settings = with_overrides(
        Settings(), translation={"engine": "openai", "api_key": "sk-secret", "temperature": 0.3}
    )
    public = settings.to_dict()
    assert public["translation"]["api_key"] == SECRET_MASK
    assert settings.to_dict(include_secrets=True)["translation"]["api_key"] == "sk-secret"
    restored = Settings.from_dict(public)
    assert restored.translation.engine == "openai" and restored.translation.api_key is None
    assert restored.translation.temperature == 0.3
    assert Settings.from_dict(settings.to_dict(include_secrets=True)) == settings


def test_glossary_loading(tmp_path: Path) -> None:
    file = tmp_path / "g.toml"
    file.write_text('[terms]\n"deep" = "profundo"\n', encoding="utf-8")
    glossary = Glossary.load(file)
    assert glossary.terms == {"deep": "profundo"} and "deep → profundo" in glossary.to_prompt()
    old = tmp_path / "old.toml"
    old.write_text('keep = ["ResNet"]\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        Glossary.load(old)


def test_language_helpers() -> None:
    assert display_name("pt-BR") == "Brazilian Portuguese"
    assert google_code("pt-BR") == "pt" and google_code("zh") == "zh-CN"
    assert hyphenation_code("pt-BR") == "pt_BR"
    assert ("pt-BR", "Brazilian Portuguese") in list_languages()
