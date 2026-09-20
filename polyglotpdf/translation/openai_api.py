"""OpenAI and OpenAI-compatible engines (official ``openai`` SDK).

* :class:`OpenAITranslator` talks to OpenAI itself through the Responses API,
  with a strict JSON schema for the answer.
* :class:`ChatCompletionsTranslator` covers every provider that implements the
  Chat Completions protocol (DeepSeek, Gemini, Mistral, xAI Grok, Qwen,
  OpenRouter, Ollama, self-hosted servers...). Providers differ in how much of
  ``response_format`` they support; when one rejects it, the engine falls back
  to plain JSON requested by the prompt.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from ..errors import (
    BatchTooLargeError,
    FatalTranslationError,
    RefusalError,
    TransientTranslationError,
)
from .llm import LLMTranslator
from .prompts import OUTPUT_SCHEMA, PROMPT_VERSION

log = logging.getLogger(__name__)

T = TypeVar("T")
_SCHEMA_NAME = "translations"
JSON_MODES = ("schema", "object", "none")


class _OpenAIBase(LLMTranslator):
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
        max_batch_items: int,
        max_batch_chars: int,
        client: Any | None,
    ) -> None:
        if client is None:
            try:
                import openai
            except ImportError as exc:  # pragma: no cover - dependency is declared
                raise FatalTranslationError("The 'openai' package is not installed") from exc
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
        self.max_batch_items = max_batch_items
        self.max_batch_chars = max_batch_chars

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()

    def _call(self, request: Callable[[], T]) -> T:
        """Run a request, translating SDK errors into the package's error types.

        ``BadRequestError`` is re-raised unchanged: callers decide what it means.
        """
        import openai

        label = self.label
        try:
            return request()
        except openai.AuthenticationError as exc:
            raise FatalTranslationError(f"{label}: API key rejected") from exc
        except openai.PermissionDeniedError as exc:
            raise FatalTranslationError(f"{label}: access denied ({exc})") from exc
        except openai.NotFoundError as exc:
            raise FatalTranslationError(
                f"{label}: unknown model {self.model!r} or endpoint"
            ) from exc
        except openai.RateLimitError as exc:
            if _quota_exhausted(exc):
                raise FatalTranslationError(f"{label}: quota or credit exhausted") from exc
            raise TransientTranslationError(f"{label}: rate limited") from exc
        except openai.BadRequestError:
            raise
        except openai.APIStatusError as exc:
            if exc.status_code == 402:
                raise FatalTranslationError(f"{label}: insufficient balance") from exc
            if exc.status_code >= 500 or exc.status_code in (408, 409):
                raise TransientTranslationError(f"{label}: server error {exc.status_code}") from exc
            raise FatalTranslationError(f"{label}: API error {exc.status_code}: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise TransientTranslationError(f"{label}: network error ({exc})") from exc


class OpenAITranslator(_OpenAIBase):
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
        timeout: float = 600.0,
        max_retries: int = 4,
        max_batch_items: int = 40,
        max_batch_chars: int = 7000,
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
            max_batch_items=max_batch_items,
            max_batch_chars=max_batch_chars,
            client=client,
        )

    def fingerprint(self) -> str:
        return f"openai/{self.model}/prompt-{PROMPT_VERSION}"

    def _complete(self, system: str, user: str) -> str:
        import openai

        params: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": user,
            "max_output_tokens": self.max_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": _SCHEMA_NAME,
                    "schema": OUTPUT_SCHEMA,
                    "strict": True,
                }
            },
        }
        if self.temperature is not None:
            params["temperature"] = self.temperature
        try:
            response = self._call(lambda: self._client.responses.create(**params))
        except openai.BadRequestError as exc:
            raise FatalTranslationError(f"OpenAI rejected the request: {exc}") from exc
        if getattr(response, "status", "completed") == "incomplete":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            if reason == "content_filter":
                raise RefusalError("OpenAI content filter")
            raise BatchTooLargeError(f"Response incomplete ({reason})")
        text = _response_text(response)
        if not text:
            raise TransientTranslationError("OpenAI returned an empty answer")
        return text


class ChatCompletionsTranslator(_OpenAIBase):
    """Any provider implementing the OpenAI Chat Completions protocol."""

    def __init__(
        self,
        *,
        name: str,
        label: str,
        model: str,
        base_url: str,
        api_key: str | None = None,
        json_mode: str = "object",
        token_param: str = "max_tokens",
        temperature: float | None = None,
        max_tokens: int = 8192,
        max_concurrency: int | None = None,
        timeout: float = 600.0,
        max_retries: int = 4,
        max_batch_items: int = 40,
        max_batch_chars: int = 7000,
        client: Any | None = None,
    ) -> None:
        if json_mode not in JSON_MODES:
            raise ValueError(f"json_mode must be one of {JSON_MODES}")
        super().__init__(
            model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
            max_batch_items=max_batch_items,
            max_batch_chars=max_batch_chars,
            client=client,
        )
        self.name = name
        self.label = label
        self.json_mode = json_mode
        self.token_param = token_param
        self.max_concurrency = max_concurrency

    def fingerprint(self) -> str:
        return f"{self.name}/{self.model}/prompt-{PROMPT_VERSION}"

    def _request(self, system: str, user: str) -> Any:
        params = self._params(system, user)
        return self._call(lambda: self._client.chat.completions.create(**params))

    def _complete(self, system: str, user: str) -> str:
        import openai

        while True:
            try:
                response = self._request(system, user)
                break
            except openai.BadRequestError as exc:
                if self.json_mode != "none" and _mentions_format(exc):
                    log.info(
                        "%s rejected response_format=%s; asking for JSON in the prompt only",
                        self.label,
                        self.json_mode,
                    )
                    self.json_mode = "none"
                    continue
                raise FatalTranslationError(f"{self.label} rejected the request: {exc}") from exc

        choices = getattr(response, "choices", None) or []
        if not choices:
            raise TransientTranslationError(f"{self.label} returned no choices")
        choice = choices[0]
        finish = getattr(choice, "finish_reason", None)
        if finish == "length":
            raise BatchTooLargeError(f"{self.label}: response truncated")
        if finish == "content_filter":
            raise RefusalError(f"{self.label}: content filter")
        message = choice.message
        content = getattr(message, "content", None)
        if not content:
            refusal = getattr(message, "refusal", None)
            if refusal:
                raise RefusalError(f"{self.label}: {refusal}")
            raise TransientTranslationError(f"{self.label} returned an empty answer")
        return str(content)

    def _params(self, system: str, user: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            self.token_param: self.max_tokens,
        }
        if self.json_mode == "schema":
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": _SCHEMA_NAME, "schema": OUTPUT_SCHEMA, "strict": True},
            }
        elif self.json_mode == "object":
            params["response_format"] = {"type": "json_object"}
        if self.temperature is not None:
            params["temperature"] = self.temperature
        return params


def _response_text(response: Any) -> str | None:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text:
        return text
    for item in getattr(response, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            kind = getattr(part, "type", "")
            if kind == "refusal":
                raise RefusalError(f"OpenAI: {getattr(part, 'refusal', 'refused')}")
            if kind == "output_text":
                return str(getattr(part, "text", ""))
    return None


def _quota_exhausted(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    return code == "insufficient_quota" or "quota" in str(exc).lower()


def _mentions_format(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(word in text for word in ("response_format", "json", "schema"))
