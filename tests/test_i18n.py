"""The application's texts in the interface's language (no network)."""

import pytest

from polyglotpdf.app.i18n import engine_text, language, msg, normalize, use_language
from polyglotpdf.app.preferences import Preferences
from polyglotpdf.app.state import nothing_translated
from polyglotpdf.errors import ConfigError
from polyglotpdf.translation.engines import get_engine


@pytest.fixture(autouse=True)
def portuguese_again() -> object:
    yield
    use_language(None)


def test_any_english_is_english_and_the_rest_portuguese() -> None:
    assert normalize("en") == normalize("en-GB") == "en"
    assert normalize("pt-BR") == normalize(None) == normalize("de") == "pt-BR"


def test_messages_follow_the_current_language() -> None:
    assert msg("due.tomorrow") == "amanhã"
    use_language("en")
    assert language() == "en" and msg("due.tomorrow") == "tomorrow"
    assert msg("due.days", n=3) == "in 3 days"
    # An explicit language wins over the current one (a job that outlived its request).
    assert msg("due.tomorrow", "pt-BR") == "amanhã"


def test_engines_are_named_in_the_interface_language() -> None:
    google = get_engine("google")
    assert engine_text(google)[0] == "Google Tradutor"
    use_language("en")
    label, description = engine_text(google)
    assert label == "Google Translate" and "no API key" in description


def test_nothing_translated_speaks_the_language_the_job_started_in() -> None:
    report = {"failures": ["p1b0: Google Translate refused the request (too many requests)"]}
    assert nothing_translated("Google", report, "en").startswith("Nothing was translated")
    assert "excesso de uso" in nothing_translated("Google", report, "pt-BR")


def test_the_interface_language_is_a_preference() -> None:
    assert Preferences().interface_language == "auto"
    assert Preferences.from_dict({"interface_language": "en"}).interface_language == "en"
    with pytest.raises(ConfigError):
        Preferences.from_dict({"interface_language": "fr"})
