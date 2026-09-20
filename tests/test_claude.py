"""Anthropic engine tests with a fake client (no network)."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from polyglotpdf.errors import BatchTooLargeError, RefusalError
from polyglotpdf.translation.anthropic_api import FALLBACK_BETA, AnthropicTranslator
from polyglotpdf.translation.base import TranslationContext, TranslationRequest
from polyglotpdf.translation.glossary import Glossary


class FakeMessages:
    def __init__(self, stop_reason: str = "end_turn") -> None:
        self.calls: list[dict[str, Any]] = []
        self.stop_reason = stop_reason

    def create(self, **params: Any) -> Any:
        self.calls.append(params)
        content = params["messages"][0]["content"]
        payload = json.loads(content.split("\n", 1)[1].split("\n\n")[0])
        body = {"translations": [{"id": i["id"], "text": f"T:{i['text']}"} for i in payload]}
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            stop_details=None,
            usage=None,
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=json.dumps(body)),
            ],
        )


def translator(
    model: str = "claude-opus-5", **kwargs: Any
) -> tuple[AnthropicTranslator, FakeMessages]:
    messages = FakeMessages(**kwargs)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return AnthropicTranslator(model=model, effort="medium", client=client), messages


REQUESTS = [
    TranslationRequest("a", "Hello {v1}", "paragraph"),
    TranslationRequest("b", "Title", "heading"),
]
CONTEXT = TranslationContext("en", "pt-BR", Glossary(terms={"deep": "profundo"}), "A Paper")


def test_translates_and_maps_ids_back() -> None:
    engine, _ = translator()
    assert engine.translate_batch(REQUESTS, CONTEXT) == ["T:Hello {v1}", "T:Title"]


def test_request_parameters_for_opus() -> None:
    engine, messages = translator()
    engine.translate_batch(REQUESTS, CONTEXT)
    params = messages.calls[0]
    system = params["system"][0]["text"]
    assert params["model"] == "claude-opus-5"
    assert params["output_config"]["effort"] == "medium"
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Brazilian Portuguese" in system and "A Paper" in system
    assert "deep → profundo" in system
    assert "original language" not in system  # no word-preservation rules any more
    assert params["betas"] == [FALLBACK_BETA] and params["fallbacks"] == "default"


def test_fallbacks_and_effort_only_where_supported() -> None:
    engine, messages = translator("claude-sonnet-5")
    engine.translate_batch(REQUESTS, CONTEXT)
    assert "fallbacks" not in messages.calls[0] and "effort" in messages.calls[0]["output_config"]
    engine, messages = translator("claude-haiku-4-5")
    engine.translate_batch(REQUESTS, CONTEXT)
    assert "effort" not in messages.calls[0]["output_config"]


def test_strict_mode_adds_a_reminder() -> None:
    engine, messages = translator()
    engine.translate_batch(REQUESTS, CONTEXT.as_strict())
    assert "previous attempt" in messages.calls[0]["messages"][0]["content"]


def test_refusal_and_truncation_are_signalled() -> None:
    engine, _ = translator(stop_reason="refusal")
    with pytest.raises(RefusalError):
        engine.translate_batch(REQUESTS, CONTEXT)
    engine, _ = translator(stop_reason="max_tokens")
    with pytest.raises(BatchTooLargeError):
        engine.translate_batch(REQUESTS, CONTEXT)
