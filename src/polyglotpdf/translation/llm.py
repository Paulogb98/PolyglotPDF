"""Shared batch protocol for engines driven by large language models.

A batch is sent as a JSON array of ``{"id", "role", "text"}`` objects after a
system prompt that explains the markup; the answer must be
``{"translations": [{"id", "text"}]}``. Providers only implement
:meth:`LLMTranslator._complete`.
"""

from __future__ import annotations

import abc
import json
import re
from collections.abc import Sequence
from typing import Any

from ..errors import TransientTranslationError
from .base import TranslationContext, TranslationRequest, Translator
from .prompts import build_system_prompt, build_user_message

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class LLMTranslator(Translator):
    supports_glossary = True

    def translate_batch(
        self, requests: Sequence[TranslationRequest], context: TranslationContext
    ) -> list[str | None]:
        # Short sequential ids keep the payload compact; they are mapped back below.
        ids = [str(i) for i in range(1, len(requests) + 1)]
        numbered = [
            TranslationRequest(uid, r.text, r.role) for uid, r in zip(ids, requests, strict=True)
        ]
        answer = self._complete(
            build_system_prompt(context), build_user_message(numbered, strict=context.strict)
        )
        return parse_translations(answer, ids)

    @abc.abstractmethod
    def _complete(self, system: str, user: str) -> str:
        """Send one request and return the model's text answer (a JSON document)."""


def parse_translations(answer: str, ids: Sequence[str]) -> list[str | None]:
    """Map a JSON answer back to the request ids (missing items become ``None``)."""
    data = _load_json(answer)
    if isinstance(data, dict):
        items = data.get("translations", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []
    by_id: dict[str, str] = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            uid, text = item.get("id"), item.get("text")
            if isinstance(uid, str | int) and isinstance(text, str):
                by_id[str(uid)] = text
    return [by_id.get(uid) for uid in ids]


def _load_json(answer: str) -> Any:
    text = answer.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise TransientTranslationError("The model did not return valid JSON")
