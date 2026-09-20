"""Anthropic Claude engine (official ``anthropic`` SDK).

Requests use structured outputs, so every batch comes back as a JSON object
keyed by segment id, and the system prompt is marked for prompt caching.
"""

from __future__ import annotations

import logging
from typing import Any

from ..errors import (
    BatchTooLargeError,
    FatalTranslationError,
    RefusalError,
    TransientTranslationError,
)
from .llm import LLMTranslator
from .prompts import OUTPUT_SCHEMA, PROMPT_VERSION

log = logging.getLogger(__name__)

#: Server-side refusal fallback: a declined request is re-run on the model Anthropic
#: recommends for that refusal category, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
_FALLBACK_MODELS = frozenset({"claude-opus-5", "claude-fable-5-1"})
_NO_EFFORT_PREFIXES = ("claude-haiku", "claude-sonnet-4-5", "claude-3")


class AnthropicTranslator(LLMTranslator):
    name = "anthropic"

    def __init__(
        self,
        model: str,
        effort: str = "medium",
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 16000,
        timeout: float = 600.0,
        max_retries: int = 4,
        max_batch_items: int = 40,
        max_batch_chars: int = 7000,
        client: Any | None = None,
    ) -> None:
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - dependency is declared
                raise FatalTranslationError("The 'anthropic' package is not installed") from exc
            # Without an explicit key the SDK uses ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN
            # or an `ant auth login` profile. It retries 408/409/429/5xx with backoff.
            try:
                client = anthropic.Anthropic(
                    api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries
                )
            except anthropic.AnthropicError as exc:
                raise FatalTranslationError(f"Anthropic: {exc}") from exc
        self._client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.max_batch_items = max_batch_items
        self.max_batch_chars = max_batch_chars

    def fingerprint(self) -> str:
        return f"anthropic/{self.model}/{self.effort}/prompt-{PROMPT_VERSION}"

    def _complete(self, system: str, user: str) -> str:
        response = self._create(self._params(system, user))
        if response.stop_reason == "refusal":
            raise RefusalError(f"Claude declined the batch ({_refusal_category(response)})")
        if response.stop_reason == "max_tokens":
            raise BatchTooLargeError("Response truncated at max_tokens")
        usage = getattr(response, "usage", None)
        if usage is not None:
            log.debug(
                "anthropic usage: input=%s cache_read=%s cache_write=%s output=%s",
                getattr(usage, "input_tokens", "?"),
                getattr(usage, "cache_read_input_tokens", "?"),
                getattr(usage, "cache_creation_input_tokens", "?"),
                getattr(usage, "output_tokens", "?"),
            )
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), None)
        if text is None:
            raise TransientTranslationError("Response without a text block")
        return str(text)

    def _params(self, system: str, user: str) -> dict[str, Any]:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}
        if not self.model.startswith(_NO_EFFORT_PREFIXES):
            output_config["effort"] = self.effort
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
        }
        if self.model in _FALLBACK_MODELS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    def _create(self, params: dict[str, Any]) -> Any:
        import anthropic

        try:
            return self._client.beta.messages.create(**params)
        except anthropic.AuthenticationError as exc:
            raise FatalTranslationError(
                "Anthropic: authentication failed; check the API key (ANTHROPIC_API_KEY)"
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise FatalTranslationError(f"Anthropic: access denied ({exc})") from exc
        except anthropic.NotFoundError as exc:
            raise FatalTranslationError(f"Anthropic: unknown model {self.model!r}") from exc
        except anthropic.BadRequestError as exc:
            raise FatalTranslationError(f"Anthropic rejected the request: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise TransientTranslationError("Anthropic: rate limited") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientTranslationError(
                    f"Anthropic: server error {exc.status_code}"
                ) from exc
            raise FatalTranslationError(f"Anthropic: API error {exc.status_code}: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise TransientTranslationError(f"Anthropic: network error ({exc})") from exc

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()


def _refusal_category(response: Any) -> str:
    details = getattr(response, "stop_details", None)
    return str(getattr(details, "category", None) or "no category")
