"""OpenAI and OpenAI-compatible engines with fake clients (no network)."""

import json
from types import SimpleNamespace
from typing import Any

import httpx2
import openai
import pytest

from polyglotpdf.errors import (
    BatchTooLargeError,
    FatalTranslationError,
    RefusalError,
    TransientTranslationError,
)
from polyglotpdf.translation.base import TranslationContext, TranslationRequest
from polyglotpdf.translation.llm import parse_translations
from polyglotpdf.translation.openai_api import ChatCompletionsTranslator, OpenAITranslator

REQUESTS = [TranslationRequest("a", "Hello {v1}"), TranslationRequest("b", "World")]
CONTEXT = TranslationContext("en", "pt-BR")


def _answer(params: dict[str, Any], *, fenced: bool = False) -> str:
    user = params["messages"][-1]["content"] if "messages" in params else params["input"]
    payload = json.loads(user.split("\n", 1)[1].split("\n\n")[0])
    body = json.dumps(
        {"translations": [{"id": i["id"], "text": f"T:{i['text']}"} for i in payload]}
    )
    return f"```json\n{body}\n```" if fenced else body


def _status_error(cls: type[openai.APIStatusError], status: int, message: str) -> Exception:
    request = httpx2.Request("POST", "https://example.test/v1/chat/completions")
    return cls(message, response=httpx2.Response(status, request=request), body=None)


class FakeChat:
    def __init__(self, *, finish: str = "stop", errors: list[Exception] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.finish = finish
        self.errors = list(errors or [])

    def create(self, **params: Any) -> Any:
        self.calls.append(params)
        if self.errors:
            raise self.errors.pop(0)
        message = SimpleNamespace(content=_answer(params, fenced=True), refusal=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason=self.finish, message=message)]
        )


def chat_engine(
    json_mode: str = "object", **kwargs: Any
) -> tuple[ChatCompletionsTranslator, FakeChat]:
    chat = FakeChat(**kwargs)
    client = SimpleNamespace(chat=SimpleNamespace(completions=chat))
    engine = ChatCompletionsTranslator(
        name="deepseek",
        label="DeepSeek",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key="key",
        json_mode=json_mode,
        client=client,
    )
    return engine, chat


def test_chat_completions_request_and_fenced_json_answer() -> None:
    engine, chat = chat_engine()
    assert engine.translate_batch(REQUESTS, CONTEXT) == ["T:Hello {v1}", "T:World"]
    params = chat.calls[0]
    assert params["model"] == "deepseek-v4-flash"
    assert params["response_format"] == {"type": "json_object"}
    assert params["max_tokens"] == 8192
    assert [m["role"] for m in params["messages"]] == ["system", "user"]
    assert engine.fingerprint().startswith("deepseek/deepseek-v4-flash/")


def test_schema_mode_sends_a_json_schema() -> None:
    engine, chat = chat_engine(json_mode="schema")
    engine.translate_batch(REQUESTS, CONTEXT)
    assert chat.calls[0]["response_format"]["type"] == "json_schema"


def test_unsupported_response_format_falls_back_to_prompt_only_json() -> None:
    rejection = _status_error(openai.BadRequestError, 400, "response_format is not supported")
    engine, chat = chat_engine(errors=[rejection])
    assert engine.translate_batch(REQUESTS, CONTEXT) == ["T:Hello {v1}", "T:World"]
    assert "response_format" in chat.calls[0] and "response_format" not in chat.calls[1]
    assert engine.json_mode == "none"


def test_finish_reasons_are_signalled() -> None:
    engine, _ = chat_engine(finish="length")
    with pytest.raises(BatchTooLargeError):
        engine.translate_batch(REQUESTS, CONTEXT)
    engine, _ = chat_engine(finish="content_filter")
    with pytest.raises(RefusalError):
        engine.translate_batch(REQUESTS, CONTEXT)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_status_error(openai.AuthenticationError, 401, "bad key"), FatalTranslationError),
        (
            _status_error(openai.RateLimitError, 429, "You exceeded your current quota"),
            FatalTranslationError,
        ),
        (_status_error(openai.RateLimitError, 429, "Too many requests"), TransientTranslationError),
        (_status_error(openai.InternalServerError, 503, "overloaded"), TransientTranslationError),
        (_status_error(openai.APIStatusError, 402, "Insufficient Balance"), FatalTranslationError),
        (_status_error(openai.BadRequestError, 400, "invalid messages"), FatalTranslationError),
    ],
)
def test_errors_are_mapped(error: Exception, expected: type[Exception]) -> None:
    engine, _ = chat_engine(json_mode="none", errors=[error])
    with pytest.raises(expected):
        engine.translate_batch(REQUESTS, CONTEXT)


class FakeResponses:
    def __init__(self, status: str = "completed", reason: str | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.status, self.reason = status, reason

    def create(self, **params: Any) -> Any:
        self.calls.append(params)
        return SimpleNamespace(
            status=self.status,
            incomplete_details=SimpleNamespace(reason=self.reason),
            output_text=_answer(params),
            output=[],
        )


def responses_engine(**kwargs: Any) -> tuple[OpenAITranslator, FakeResponses]:
    responses = FakeResponses(**kwargs)
    engine = OpenAITranslator("gpt-5.6-terra", client=SimpleNamespace(responses=responses))
    return engine, responses


def test_openai_uses_the_responses_api_with_a_strict_schema() -> None:
    engine, responses = responses_engine()
    assert engine.translate_batch(REQUESTS, CONTEXT) == ["T:Hello {v1}", "T:World"]
    params = responses.calls[0]
    assert params["model"] == "gpt-5.6-terra"
    assert "Brazilian Portuguese" in params["instructions"]
    assert params["text"]["format"]["type"] == "json_schema"
    assert params["text"]["format"]["strict"] is True
    assert params["max_output_tokens"] == 16000
    assert "temperature" not in params


def test_incomplete_responses_are_signalled() -> None:
    engine, _ = responses_engine(status="incomplete", reason="max_output_tokens")
    with pytest.raises(BatchTooLargeError):
        engine.translate_batch(REQUESTS, CONTEXT)
    engine, _ = responses_engine(status="incomplete", reason="content_filter")
    with pytest.raises(RefusalError):
        engine.translate_batch(REQUESTS, CONTEXT)


def test_parse_translations_tolerates_prose_around_the_json() -> None:
    answer = 'Sure! {"translations": [{"id": "1", "text": "um"}]} Hope it helps.'
    assert parse_translations(answer, ["1", "2"]) == ["um", None]
    with pytest.raises(TransientTranslationError):
        parse_translations("no json here", ["1"])
