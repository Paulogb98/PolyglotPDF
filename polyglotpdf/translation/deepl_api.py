"""DeepL engine (official ``deepl`` SDK).

DeepL understands XML markup: placeholders become empty ``<x i="N"/>`` elements
and style tags stay as ``<b>``, ``<i>``, ``<c>``, so the markup survives the
translation reliably.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from typing import Any
from xml.sax.saxutils import escape

from ..errors import ConfigError, FatalTranslationError, TransientTranslationError
from .base import TranslationContext, TranslationRequest, Translator
from .languages import deepl_source, deepl_target

_MARKUP = re.compile(r"\{\s*[vV]\s*(\d+)\s*\}|<\s*(/?)\s*([bicBIC])\s*>")
_XML_PLACEHOLDER = re.compile(r'<x\s+i="(\d+)"\s*/>|<x\s+i="(\d+)"\s*>\s*</x>')


def to_xml(markup: str) -> str:
    """Placeholder/tag markup -> XML accepted by DeepL (plain text is escaped)."""
    out: list[str] = []
    pos = 0
    for match in _MARKUP.finditer(markup):
        out.append(escape(markup[pos : match.start()]))
        pos = match.end()
        if match.group(1) is not None:
            out.append(f'<x i="{match.group(1)}"/>')
        else:
            out.append(f"<{match.group(2)}{match.group(3).lower()}>")
    out.append(escape(markup[pos:]))
    return "".join(out)


def from_xml(text: str) -> str:
    """XML answer -> placeholder/tag markup."""
    restored = _XML_PLACEHOLDER.sub(lambda m: f"{{v{m.group(1) or m.group(2)}}}", text)
    return html.unescape(restored)


class DeepLTranslator(Translator):
    name = "deepl"
    max_batch_items = 50
    max_batch_chars = 20000
    max_concurrency = 2

    def __init__(
        self,
        api_key: str | None,
        *,
        server_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        if client is None:
            if not api_key:
                raise ConfigError("DeepL needs an API key (DEEPL_AUTH_KEY)")
            try:
                import deepl
            except ImportError as exc:  # pragma: no cover - dependency is declared
                raise FatalTranslationError("The 'deepl' package is not installed") from exc
            client = deepl.Translator(api_key, server_url=server_url)
        self._client = client

    def fingerprint(self) -> str:
        return "deepl/xml/1"

    def translate_batch(
        self, requests: Sequence[TranslationRequest], context: TranslationContext
    ) -> list[str | None]:
        import deepl

        texts = [to_xml(request.text) for request in requests]
        try:
            results = self._client.translate_text(
                texts,
                source_lang=deepl_source(context.source_lang),
                target_lang=deepl_target(context.target_lang),
                tag_handling="xml",
                ignore_tags=["x"],
            )
        except deepl.AuthorizationException as exc:
            raise FatalTranslationError("DeepL: API key rejected") from exc
        except deepl.QuotaExceededException as exc:
            raise FatalTranslationError("DeepL: character quota exceeded") from exc
        except (deepl.TooManyRequestsException, deepl.ConnectionException) as exc:
            raise TransientTranslationError(f"DeepL unavailable: {exc}") from exc
        except deepl.DeepLException as exc:
            raise TransientTranslationError(f"DeepL error: {exc}") from exc
        if not isinstance(results, list):
            results = [results]
        return [from_xml(result.text) for result in results]
