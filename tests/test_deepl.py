"""DeepL engine tests with a fake client (no network)."""

from types import SimpleNamespace
from typing import Any

import deepl
import pytest

from polyglotpdf.errors import FatalTranslationError, TransientTranslationError
from polyglotpdf.translation.base import TranslationContext, TranslationRequest
from polyglotpdf.translation.deepl_api import DeepLTranslator, from_xml, to_xml
from polyglotpdf.translation.languages import deepl_source, deepl_target


def test_markup_round_trips_through_xml() -> None:
    source = "a < b & {v1} is <b>bold</b> <c>code</c>"
    xml = to_xml(source)
    assert '<x i="1"/>' in xml and "&lt;" in xml and "&amp;" in xml and "<b>bold</b>" in xml
    assert from_xml(xml) == source
    assert from_xml('valor <x i="2"></x>') == "valor {v2}"


class FakeDeepL:
    def __init__(self, error: Exception | None = None) -> None:
        self.kwargs: dict[str, Any] = {}
        self.error = error

    def translate_text(self, texts: list[str], **kwargs: Any) -> list[Any]:
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return [SimpleNamespace(text=text.replace("value", "valor")) for text in texts]


def test_translate_batch_uses_xml_tag_handling() -> None:
    client = FakeDeepL()
    engine = DeepLTranslator(None, client=client)
    result = engine.translate_batch(
        [TranslationRequest("1", "the value {v1}")], TranslationContext("en", "pt-BR")
    )
    assert result == ["the valor {v1}"]
    assert client.kwargs["tag_handling"] == "xml" and client.kwargs["ignore_tags"] == ["x"]
    assert client.kwargs["target_lang"] == "PT-BR" and client.kwargs["source_lang"] == "EN"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (deepl.AuthorizationException("bad key"), FatalTranslationError),
        (deepl.QuotaExceededException("quota"), FatalTranslationError),
        (deepl.TooManyRequestsException("slow down"), TransientTranslationError),
        (deepl.DeepLException("server error"), TransientTranslationError),
    ],
)
def test_errors_are_mapped(error: Exception, expected: type[Exception]) -> None:
    engine = DeepLTranslator(None, client=FakeDeepL(error))
    with pytest.raises(expected):
        engine.translate_batch([TranslationRequest("1", "x")], TranslationContext("en", "pt-BR"))


def test_language_codes() -> None:
    assert deepl_target("pt-BR") == "PT-BR" and deepl_target("pt") == "PT-PT"
    assert deepl_target("en") == "EN-US" and deepl_target("zh") == "ZH-HANS"
    assert deepl_target("de") == "DE"
    assert deepl_source("auto") is None and deepl_source("en-US") == "EN"
