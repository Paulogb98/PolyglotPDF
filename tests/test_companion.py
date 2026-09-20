"""Reading companion: prompts, chat clients with fake SDK clients, factory (no network)."""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import openai
import pytest

from polyglotpdf.companion import (
    AnthropicChat,
    ChatCompletionsChat,
    ChatMessage,
    EchoChat,
    OpenAIChat,
    ReadingCompanion,
    create_chat_client,
)
from polyglotpdf.companion.prompts import context_message, follow_up_message, system_prompt
from polyglotpdf.errors import CompanionError, ConfigError
from polyglotpdf.reading import Anchor, PassageContext
from polyglotpdf.translation.engines import chat_engines

CONTEXT = PassageContext(
    title="Dom Casmurro",
    authors="Machado de Assis",
    section=("Capítulo XXXII",),
    page=41,
    page_label="42",
    page_count=250,
    selection="olhos de ressaca",
    current="Capitu deu-me as costas… olhos de ressaca…",
    before="Texto anterior.",
    after="Texto seguinte.",
    start=Anchor(41, 100),
    end=Anchor(41, 116),
)
USER = [ChatMessage("user", "oi")]


def response(status: int) -> httpx2.Response:
    return httpx2.Response(status, request=httpx2.Request("POST", "https://example.test/v1"))


# ---------------------------------------------------------------------- prompts
def test_first_message_carries_the_passage_and_its_context() -> None:
    text = context_message(CONTEXT, "context", None)
    for part in (
        "Title: Dom Casmurro",
        "Authors: Machado de Assis",
        "Section: Capítulo XXXII",
        "Page: p. 42 of 250",
        "<context_before>\nTexto anterior.",
        "<current_paragraph>",
        "<selected_passage>\nolhos de ressaca\n</selected_passage>",
        "<context_after>",
        "Task: Give the context",
    ):
        assert part in text
    follow = follow_up_message("ask", "E o que isso diz sobre Bentinho?")
    assert follow.startswith("Task: Answer") and "Bentinho" in follow and "<document>" not in follow


def test_whole_page_requests_and_validation() -> None:
    page = PassageContext.from_dict({**CONTEXT.to_dict(), "selection": ""})
    text = context_message(page, "summarize", None)
    assert "<page_text>" in text and "<selected_passage>" not in text
    assert "no passage selected" in text
    with pytest.raises(ConfigError):
        context_message(CONTEXT, "dance", None)
    with pytest.raises(ConfigError):
        follow_up_message("ask", "   ")
    assert "Brazilian Portuguese" in system_prompt("pt-BR")
    assert "spoilers" in system_prompt("en")


def test_companion_with_the_echo_engine() -> None:
    companion = ReadingCompanion(EchoChat(chunk=7), language="pt-BR")
    first = "".join(companion.ask(CONTEXT, "explain"))
    assert "Test mode" in first and "<selected_passage>" in first
    history = [companion.message(CONTEXT, "explain"), ChatMessage("assistant", "Resposta.")]
    later = "".join(companion.ask(CONTEXT, "ask", "Por que ressaca?", history=history))
    assert "Por que ressaca?" in later and "<document>" not in later


# ---------------------------------------------------------------------- Anthropic
class FakeAnthropicStream:
    def __init__(self, events: list[Any], stop_reason: str) -> None:
        self.events = events
        self.stop_reason = stop_reason

    def __enter__(self) -> "FakeAnthropicStream":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def __iter__(self) -> Iterator[Any]:
        return iter(self.events)

    def get_final_message(self) -> Any:
        return SimpleNamespace(stop_reason=self.stop_reason)


class FakeAnthropic:
    def __init__(
        self,
        events: list[Any] | None = None,
        stop_reason: str = "end_turn",
        error: Exception | None = None,
    ) -> None:
        self.events = events or []
        self.stop_reason = stop_reason
        self.error = error
        self.params: dict[str, Any] = {}
        self.messages = self

    def stream(self, **params: Any) -> FakeAnthropicStream:
        self.params = params
        if self.error is not None:
            raise self.error
        return FakeAnthropicStream(self.events, self.stop_reason)


def test_anthropic_streams_text_events() -> None:
    events = [
        SimpleNamespace(type="message_start"),
        SimpleNamespace(type="text", text="Olá"),
        SimpleNamespace(type="content_block_delta"),
        SimpleNamespace(type="text", text=" leitor"),
    ]
    fake = FakeAnthropic(events)
    chat = AnthropicChat("claude-opus-5", client=fake)
    assert "".join(chat.stream("sys", USER)) == "Olá leitor"
    assert fake.params["system"] == "sys"
    assert fake.params["messages"] == [{"role": "user", "content": "oi"}]
    assert fake.params["output_config"] == {"effort": "medium"}
    assert fake.params["cache_control"] == {"type": "ephemeral"}
    haiku = FakeAnthropic()
    list(AnthropicChat("claude-haiku-4-5", client=haiku).stream("s", USER))
    assert "output_config" not in haiku.params


def test_anthropic_refusals_and_errors() -> None:
    with pytest.raises(CompanionError, match="declined"):
        list(
            AnthropicChat("claude-opus-5", client=FakeAnthropic(stop_reason="refusal")).stream(
                "s", USER
            )
        )
    limited = anthropic.RateLimitError("slow down", response=response(429), body=None)
    with pytest.raises(CompanionError) as info:
        list(AnthropicChat("claude-opus-5", client=FakeAnthropic(error=limited)).stream("s", USER))
    assert info.value.retryable
    rejected = anthropic.AuthenticationError("bad key", response=response(401), body=None)
    with pytest.raises(CompanionError, match="rejected") as info:
        list(AnthropicChat("claude-opus-5", client=FakeAnthropic(error=rejected)).stream("s", USER))
    assert not info.value.retryable


# ---------------------------------------------------------------------- OpenAI family
class FakeOpenAI:
    def __init__(
        self,
        events: list[Any] | None = None,
        chunks: list[Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.events = events or []
        self.chunks = chunks or []
        self.error = error
        self.params: dict[str, Any] = {}
        self.responses = SimpleNamespace(create=self._responses)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))

    def _responses(self, **params: Any) -> Iterator[Any]:
        self.params = params
        if self.error is not None:
            raise self.error
        return iter(self.events)

    def _chat(self, **params: Any) -> Iterator[Any]:
        self.params = params
        if self.error is not None:
            raise self.error
        return iter(self.chunks)


def test_openai_responses_stream() -> None:
    events = [
        SimpleNamespace(type="response.created"),
        SimpleNamespace(type="response.output_text.delta", delta="Um"),
        SimpleNamespace(type="response.output_text.delta", delta=" dois"),
        SimpleNamespace(type="response.completed"),
    ]
    fake = FakeOpenAI(events=events)
    history = [ChatMessage("user", "a"), ChatMessage("assistant", "b"), ChatMessage("user", "c")]
    chat = OpenAIChat("gpt-5.6-terra", client=fake, temperature=0.2)
    assert "".join(chat.stream("sys", history)) == "Um dois"
    assert fake.params["instructions"] == "sys" and fake.params["stream"] is True
    assert fake.params["temperature"] == 0.2
    assert [item["role"] for item in fake.params["input"]] == ["user", "assistant", "user"]


def test_openai_refusals_and_errors() -> None:
    refusal = FakeOpenAI(events=[SimpleNamespace(type="response.refusal.delta", delta="não posso")])
    with pytest.raises(CompanionError, match="não posso"):
        list(OpenAIChat("m", client=refusal).stream("s", USER))
    rejected = openai.AuthenticationError("bad key", response=response(401), body=None)
    with pytest.raises(CompanionError, match="rejected"):
        list(OpenAIChat("m", client=FakeOpenAI(error=rejected)).stream("s", USER))


def chunk(text: str | None, finish: str | None = None) -> Any:
    delta = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)])


def test_chat_completions_stream() -> None:
    fake = FakeOpenAI(
        chunks=[chunk("Olá"), SimpleNamespace(choices=[]), chunk(None), chunk(" leitor", "stop")]
    )
    chat = ChatCompletionsChat(
        name="deepseek",
        label="DeepSeek",
        model="deepseek-v4-flash",
        base_url="https://x",
        client=fake,
    )
    assert "".join(chat.stream("sys", USER)) == "Olá leitor"
    assert fake.params["messages"][0] == {"role": "system", "content": "sys"}
    assert fake.params["messages"][1] == {"role": "user", "content": "oi"}
    assert fake.params["stream"] is True

    down = openai.InternalServerError("down", response=response(503), body=None)
    broken = ChatCompletionsChat(
        name="x", label="X", model="m", base_url="https://x", client=FakeOpenAI(error=down)
    )
    with pytest.raises(CompanionError) as info:
        list(broken.stream("s", USER))
    assert info.value.retryable and "503" in str(info.value)


# ---------------------------------------------------------------------- factory
def test_factory_and_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(create_chat_client("echo"), EchoChat)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        create_chat_client("deepseek")
    deepseek = create_chat_client("deepseek", api_key="k")
    assert isinstance(deepseek, ChatCompletionsChat) and deepseek.model == "deepseek-v4-flash"
    assert "api.deepseek.com" in str(deepseek._client.base_url)
    claude = create_chat_client("claude", api_key="k", effort="low")
    assert isinstance(claude, AnthropicChat) and claude.model == "claude-opus-5"
    assert claude.effort == "low"
    assert isinstance(create_chat_client("openai", api_key="k", model="gpt-x"), OpenAIChat)
    with pytest.raises(ConfigError):
        create_chat_client("google")
    with pytest.raises(ConfigError):
        create_chat_client("custom", model="m")
    names = {engine.name for engine in chat_engines()}
    assert {"anthropic", "openai", "deepseek", "ollama", "echo"} <= names
    assert not names & {"google", "deepl", "pseudo"}
