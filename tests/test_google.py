"""Google engine tests with fake HTTP answers (no network)."""

import json
import urllib.parse
from typing import Any

import pytest

from polyglotpdf.errors import TransientTranslationError
from polyglotpdf.segmentation.markup import repair
from polyglotpdf.translation import google
from polyglotpdf.translation.base import TranslationContext, TranslationRequest
from polyglotpdf.translation.google import GoogleTranslator, Refused, _chunks


class FakeGoogle:
    """Upper-cases text and, unless told otherwise, breaks placeholders."""

    def __init__(self, *, mangle: bool = True, refuse_html: bool = False) -> None:
        self.mangle, self.refuse_html = mangle, refuse_html
        self.html_calls: list[dict[str, Any]] = []
        self.dict_calls: list[dict[str, str]] = []

    def translate(self, text: str) -> str:
        text = text.upper()
        return text.replace("{V", "[") if self.mangle else text.replace("{V", "{v")

    def __call__(self, url: str, *, data: bytes | None = None, headers: dict[str, str]) -> str:
        if url == google.HTML_URL:
            (texts, source, target), _client = json.loads(data or b"")
            self.html_calls.append({"texts": texts, "source": source, "target": target})
            if self.refuse_html:
                raise Refused("Google Translate refused the request (too many requests)")
            # The page translator keeps tags as they came, in lower case.
            answer = [
                self.translate(text).replace("<I>", "<i>").replace("</I>", "</i>") for text in texts
            ]
            return json.dumps([answer])
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.dict_calls.append(query)
        return json.dumps([self.translate(query["q"])])


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeGoogle:
    engine = FakeGoogle()
    monkeypatch.setattr(google, "_request", engine)
    return engine


REQUEST = [TranslationRequest("1", "value {v1} is <i>large</i> here")]
CONTEXT = TranslationContext("en", "pt-BR")


def test_a_batch_is_one_request(fake: FakeGoogle) -> None:
    requests = [TranslationRequest(str(n), f"text {n}") for n in range(5)]
    results = GoogleTranslator().translate_batch(requests, CONTEXT)
    assert len(fake.html_calls) == 1 and len(fake.html_calls[0]["texts"]) == 5
    assert results == [f"TEXT {n}" for n in range(5)]


def test_normal_mode_sends_the_whole_segment(fake: FakeGoogle) -> None:
    (result,) = GoogleTranslator().translate_batch(REQUEST, CONTEXT)
    assert fake.html_calls[0]["texts"] == ["value {v1} is <i>large</i> here"]
    assert result is not None and repair(result, {1}) is None  # placeholder lost


def test_strict_mode_only_translates_text_between_markup(fake: FakeGoogle) -> None:
    (result,) = GoogleTranslator().translate_batch(REQUEST, CONTEXT.as_strict())
    assert result == "VALUE {v1} IS <i>LARGE</i> HERE"
    sent = fake.html_calls[0]["texts"]
    assert all("{" not in text and "<" not in text for text in sent)


def test_prose_angle_brackets_and_ampersands_survive(fake: FakeGoogle) -> None:
    fake.mangle = False
    request = [TranslationRequest("1", "if a < b & c then {v1}")]
    (result,) = GoogleTranslator().translate_batch(request, CONTEXT)
    assert fake.html_calls[0]["texts"] == ["if a &lt; b &amp; c then {v1}"]
    assert result == "IF A < B & C THEN {v1}"


def test_spaces_moved_around_tags_are_put_back() -> None:
    assert google._from_html("na <b>Fig. 2</b> .") == "na <b>Fig. 2</b>."
    assert google._from_html("usamos<c> SGD</c> com") == "usamos <c>SGD</c> com"


def test_language_codes_are_mapped(fake: FakeGoogle) -> None:
    GoogleTranslator().translate_batch(REQUEST, TranslationContext("auto", "pt-BR"))
    assert fake.html_calls[0]["source"] == "auto" and fake.html_calls[0]["target"] == "pt"


def test_the_single_text_endpoint_steps_in_when_the_page_translator_refuses(
    fake: FakeGoogle,
) -> None:
    fake.refuse_html, fake.mangle = True, False
    requests = [TranslationRequest("1", "a < b"), TranslationRequest("2", "second")]
    results = GoogleTranslator().translate_batch(requests, CONTEXT)
    assert [call["q"] for call in fake.dict_calls] == ["a < b", "second"]
    assert results == ["A < B", "SECOND"]


def test_refusal_everywhere_is_a_transient_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(url: str, *, data: bytes | None = None, headers: dict[str, str]) -> str:
        raise Refused("Google Translate refused the request (too many requests)")

    monkeypatch.setattr(google, "_request", refuse)
    with pytest.raises(TransientTranslationError, match="too many requests"):
        GoogleTranslator().translate_batch(REQUEST, CONTEXT)


def test_an_answer_that_is_not_a_translation_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(google, "_request", lambda url, **_: "<html>Sorry...</html>")
    with pytest.raises(TransientTranslationError):
        GoogleTranslator().translate_batch(REQUEST, CONTEXT)


def test_requests_are_sequential() -> None:
    assert GoogleTranslator.max_concurrency == 1


def test_long_texts_are_chunked_at_sentence_boundaries(fake: FakeGoogle) -> None:
    text = "A sentence. " * 1000
    chunks = _chunks(text.strip())
    assert len(chunks) > 1 and all(len(chunk) <= 4500 for chunk in chunks)
    assert " ".join(chunks) == text.strip()
    (result,) = GoogleTranslator().translate_batch([TranslationRequest("1", text)], CONTEXT)
    assert result == text.strip().upper()
