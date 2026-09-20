"""Streaming chat with the AI providers of the engine catalogue.

* :class:`AnthropicChat` — Claude through the Messages API (streamed, prompt caching).
* :class:`OpenAIChat` — OpenAI through the Responses API (streamed).
* :class:`ChatCompletionsChat` — every OpenAI-compatible provider (DeepSeek, Gemini,
  Mistral, xAI, Qwen, OpenRouter, Ollama, self-hosted servers).
* :class:`EchoChat` — offline: answers with the message it received, to inspect
  exactly what would be sent.

Provider errors become :class:`~polyglotpdf.errors.CompanionError` (``retryable``
tells whether trying again may help).
"""

from __future__ import annotations

import abc
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ..errors import CompanionError, ConfigError
from ..translation.engines import get_engine

Role = Literal["user", "assistant"]
_NO_EFFORT_PREFIXES = ("claude-haiku", "claude-sonnet-4-5", "claude-3")


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


class ChatClient(abc.ABC):
    """A conversation-capable model."""

    name: str = "base"
    model: str = ""

    @abc.abstractmethod
    def stream(self, system: str, messages: Sequence[ChatMessage]) -> Iterator[str]:
        """Yield the assistant's answer in pieces; failures raise :class:`CompanionError`."""

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release network resources."""


# ---------------------------------------------------------------------- Anthropic
class AnthropicChat(ChatClient):
    name = "anthropic"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        effort: str | None = "medium",
        max_tokens: int = 8192,
        timeout: float = 180.0,
        max_retries: int = 2,
        client: Any | None = None,
    ) -> None:
        if client is None:
            import anthropic

            try:
                client = anthropic.Anthropic(
                    api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries
                )
            except anthropic.AnthropicError as exc:
                raise CompanionError(f"Anthropic: {exc}") from exc
        self._client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def stream(self, system: str, messages: Sequence[ChatMessage]) -> Iterator[str]:
        import anthropic

        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            # Follow-up questions resend the passage: cache the conversation prefix.
            "cache_control": {"type": "ephemeral"},
        }
        if self.effort and not self.model.startswith(_NO_EFFORT_PREFIXES):
            params["output_config"] = {"effort": self.effort}
        try:
            with self._client.messages.stream(**params) as stream:
                for event in stream:
                    if getattr(event, "type", "") == "text":
                        yield str(getattr(event, "text", ""))
                final = stream.get_final_message()
        except anthropic.APIError as exc:
            raise _anthropic_error(exc) from exc
        if getattr(final, "stop_reason", None) == "refusal":
            raise CompanionError("Claude declined to answer about this passage")

    def close(self) -> None:
        _close(self._client)


def _anthropic_error(exc: Exception) -> CompanionError:
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return CompanionError("Anthropic: API key rejected")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return CompanionError(f"Anthropic: access denied ({exc})")
    if isinstance(exc, anthropic.NotFoundError):
        return CompanionError("Anthropic: unknown model")
    if isinstance(exc, anthropic.RateLimitError):
        return CompanionError("Anthropic: rate limited, try again shortly", retryable=True)
    if isinstance(exc, anthropic.APIStatusError):
        retryable = exc.status_code >= 500
        return CompanionError(f"Anthropic: API error {exc.status_code}", retryable=retryable)
    return CompanionError(f"Anthropic: network error ({exc})", retryable=True)


# ---------------------------------------------------------------------- OpenAI family
class _OpenAIChatBase(ChatClient):
    label = "OpenAI"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None,
        base_url: str | None,
        temperature: float | None,
        max_tokens: int,
        timeout: float,
        max_retries: int,
        client: Any | None,
    ) -> None:
        if client is None:
            import openai

            client = openai.OpenAI(
                api_key=api_key or "not-needed",  # local servers accept any key
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
            )
        self._client = client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def close(self) -> None:
        _close(self._client)

    def _error(self, exc: Exception) -> CompanionError:
        import openai

        label = self.label
        if isinstance(exc, openai.AuthenticationError):
            return CompanionError(f"{label}: API key rejected")
        if isinstance(exc, openai.PermissionDeniedError):
            return CompanionError(f"{label}: access denied ({exc})")
        if isinstance(exc, openai.NotFoundError):
            return CompanionError(f"{label}: unknown model {self.model!r} or endpoint")
        if isinstance(exc, openai.RateLimitError):
            if "quota" in str(exc).lower():
                return CompanionError(f"{label}: quota or credit exhausted")
            return CompanionError(f"{label}: rate limited, try again shortly", retryable=True)
        if isinstance(exc, openai.BadRequestError):
            return CompanionError(f"{label} rejected the request: {exc}")
        if isinstance(exc, openai.APIStatusError):
            if exc.status_code == 402:
                return CompanionError(f"{label}: insufficient balance")
            retryable = exc.status_code >= 500 or exc.status_code in (408, 409)
            return CompanionError(f"{label}: API error {exc.status_code}", retryable=retryable)
        return CompanionError(f"{label}: network error ({exc})", retryable=True)


class OpenAIChat(_OpenAIChatBase):
    """OpenAI models through the Responses API."""

    name = "openai"
    label = "OpenAI"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 16000,
        timeout: float = 180.0,
        max_retries: int = 2,
        client: Any | None = None,
    ) -> None:
        super().__init__(
            model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
            client=client,
        )

    def stream(self, system: str, messages: Sequence[ChatMessage]) -> Iterator[str]:
        import openai

        params: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": [{"role": m.role, "content": m.content} for m in messages],
            "max_output_tokens": self.max_tokens,
            "stream": True,
        }
        if self.temperature is not None:
            params["temperature"] = self.temperature
        refusal: list[str] = []
        try:
            for event in self._client.responses.create(**params):
                kind = getattr(event, "type", "")
                if kind == "response.output_text.delta":
                    yield str(event.delta)
                elif kind == "response.refusal.delta":
                    refusal.append(str(event.delta))
                elif kind in ("response.failed", "error"):
                    raise CompanionError(f"OpenAI: the answer failed ({_event_message(event)})")
        except openai.OpenAIError as exc:
            raise self._error(exc) from exc
        if refusal:
            raise CompanionError(f"OpenAI declined: {''.join(refusal)}")


class ChatCompletionsChat(_OpenAIChatBase):
    """Any provider implementing the OpenAI Chat Completions protocol."""

    def __init__(
        self,
        *,
        name: str,
        label: str,
        model: str,
        base_url: str,
        api_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 8192,
        timeout: float = 180.0,
        max_retries: int = 2,
        client: Any | None = None,
    ) -> None:
        super().__init__(
            model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
            client=client,
        )
        self.name = name
        self.label = label

    def stream(self, system: str, messages: Sequence[ChatMessage]) -> Iterator[str]:
        import openai

        params: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                *({"role": m.role, "content": m.content} for m in messages),
            ],
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if self.temperature is not None:
            params["temperature"] = self.temperature
        try:
            for chunk in self._client.chat.completions.create(**params):
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                content = getattr(choices[0].delta, "content", None)
                if content:
                    yield str(content)
                if getattr(choices[0], "finish_reason", None) == "content_filter":
                    raise CompanionError(f"{self.label}: blocked by the content filter")
        except openai.OpenAIError as exc:
            raise self._error(exc) from exc


# ---------------------------------------------------------------------- offline
class EchoChat(ChatClient):
    """Answers with the last message it received (inspect the context; no network)."""

    name = "echo"
    model = "echo"

    def __init__(self, *, chunk: int = 48, delay: float = 0.0) -> None:
        self.chunk = max(1, chunk)
        self.delay = delay

    def stream(self, system: str, messages: Sequence[ChatMessage]) -> Iterator[str]:
        last = messages[-1].content if messages else ""
        text = (
            "**Test mode (Echo):** no AI was called. This is the message that would be "
            f"sent to the model:\n\n```text\n{last}\n```\n"
        )
        for begin in range(0, len(text), self.chunk):
            if self.delay:
                time.sleep(self.delay)
            yield text[begin : begin + self.chunk]


# ---------------------------------------------------------------------- factory
def create_chat_client(
    engine: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    effort: str | None = "medium",
    temperature: float | None = None,
    timeout: float = 180.0,
) -> ChatClient:
    """Chat client for an engine of the catalogue (see ``chat_engines()``)."""
    info = get_engine(engine)
    if not info.supports_chat:
        raise ConfigError(f"{info.label} cannot be used by the reading companion")
    if info.name == "echo":
        return EchoChat()
    key = info.api_key(api_key)
    if info.requires_key and not key and info.name != "anthropic":
        # (Claude may also authenticate with an `ant auth login` profile.)
        raise ConfigError(f"{info.label} needs an API key: set it or {' or '.join(info.key_env)}")
    chosen = model or info.default_model
    if not chosen:
        raise ConfigError(f"{info.label}: choose a model")
    if info.name == "anthropic":
        return AnthropicChat(chosen, api_key=key, base_url=base_url, effort=effort, timeout=timeout)
    if info.name == "openai":
        return OpenAIChat(
            chosen, api_key=key, base_url=base_url, temperature=temperature, timeout=timeout
        )
    url = base_url or info.base_url
    if not url:
        raise ConfigError(f"{info.label}: base_url is required")
    return ChatCompletionsChat(
        name=info.name,
        label=info.label,
        model=chosen,
        base_url=url,
        api_key=key,
        temperature=temperature,
        timeout=timeout,
    )


def _event_message(event: Any) -> str:
    error = getattr(event, "error", None) or getattr(
        getattr(event, "response", None), "error", None
    )
    return str(getattr(error, "message", None) or error or "unknown error")


def _close(client: Any) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        close()
