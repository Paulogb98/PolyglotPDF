"""Google Translate engine (free web endpoints, no key).

Requests go to the endpoint Google's own page translator uses (Chrome and the website
widget): ``translateHtml`` takes a batch of HTML strings and keeps the tags in place,
so style tags travel as tags and a whole batch is a single request. Google answers
addresses it considers automated with ``429`` and a "Sorry..." page; each endpoint
refuses independently, so when ``translateHtml`` refuses, the single-text endpoint of
the dictionary extension is tried before giving up.

The engine cannot follow instructions: names and titles of works may be translated.
Terms listed under ``keep`` in the glossary are protected with placeholders before the
text is sent. Google occasionally mangles placeholders in formula-heavy sentences; on
the strict retry only the text *between* placeholders and style tags is sent, so the
markup cannot be lost (at the cost of translating shorter fragments).
"""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence

from ..errors import TransientTranslationError
from .base import TranslationContext, TranslationRequest, Translator
from .languages import google_code

log = logging.getLogger(__name__)

HTML_URL = "https://translate-pa.googleapis.com/v1/translateHtml"
#: Google's own key, published inside the script its website translator widget loads
#: (``el_main``); it belongs to nobody here and there is nothing to revoke. GitHub secret
#: scanning matches the ``AIza...`` shape and flags it anyway: dismiss that alert.
HTML_KEY = "AIzaSyATBXajvzQLTDHEQbcpq0Ihe0vWDHmO520"
DICT_URL = "https://clients5.google.com/translate_a/t"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)
_TIMEOUT = 60

_MAX_CHARS = 4500  # longer texts are split at sentence boundaries
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+")
_MARKUP = re.compile(r"(\{\s*[vV]\s*\d+\s*\}|<\s*/?\s*[bicBIC]\s*>)")
_LETTER = re.compile(r"[^\W\d_]")
# The page translator moves spaces around tags: "Fig. 2</b> ." and "usamos<c> SGD</c>".
_SPACE_AFTER_CLOSE = re.compile(r"(</[bic]>)\s+(?=[.,;:!?)\]])")
_SPACE_INSIDE_OPEN = re.compile(r"(?<=\S)(<[bic]>)\s+")
_SPACE_INSIDE_CLOSE = re.compile(r"\s+(</[bic]>)(?=\S)")
_SPACES = re.compile(r"[ \t]{2,}")


class Refused(TransientTranslationError):
    """The endpoint turned the request down (throttled, blocked or failing)."""


def _request(url: str, *, data: bytes | None = None, headers: dict[str, str]) -> str:
    """One HTTP request; the body as text. Network and HTTP errors become ``Refused``."""
    request = urllib.request.Request(url, data=data, headers={"User-Agent": _USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return str(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        reason = "too many requests" if exc.code == 429 else f"HTTP {exc.code}"
        raise Refused(f"Google Translate refused the request ({reason})") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise Refused(f"Google Translate could not be reached ({exc})") from exc


def translate_html(texts: list[str], source: str, target: str) -> list[str]:
    """Translate HTML strings with the page translator's endpoint (one request)."""
    body = json.dumps([[texts, source, target], "te_lib"]).encode("utf-8")
    raw = _request(
        HTML_URL,
        data=body,
        headers={"Content-Type": "application/json+protobuf", "X-Goog-API-Key": HTML_KEY},
    )
    try:
        translated = json.loads(raw)[0]
    except (ValueError, IndexError, TypeError) as exc:
        raise Refused("Google Translate answered with something that is not a translation") from exc
    if not isinstance(translated, list) or len(translated) != len(texts):
        raise Refused("Google Translate answered a different number of texts")
    return [str(text or "") for text in translated]


def translate_text(text: str, source: str, target: str) -> str:
    """Translate one string with the dictionary extension's endpoint."""
    query = urllib.parse.urlencode(
        {"client": "dict-chrome-ex", "sl": source, "tl": target, "q": text}
    )
    raw = _request(f"{DICT_URL}?{query}", headers={})
    try:
        item = json.loads(raw)[0]
    except (ValueError, IndexError, TypeError) as exc:
        raise Refused("Google Translate answered with something that is not a translation") from exc
    return str(item[0] if isinstance(item, list) else item)


class GoogleTranslator(Translator):
    name = "google"
    max_batch_items = 50
    max_batch_chars = 12000
    instructable = False
    max_concurrency = 1

    def fingerprint(self) -> str:
        return "google/web/2"

    def translate_batch(
        self, requests: Sequence[TranslationRequest], context: TranslationContext
    ) -> list[str | None]:
        source = google_code(context.source_lang)
        target = google_code(context.target_lang)
        if context.strict:
            return [self._translate_fragments(request.text, source, target) for request in requests]

        # Long texts travel as several pieces and are joined back afterwards.
        pieces: list[str] = []
        owners: list[int] = []
        for index, request in enumerate(requests):
            for chunk in _chunks(request.text):
                pieces.append(_to_html(chunk))
                owners.append(index)
        translated = self._translate_all(pieces, source, target)
        joined: list[list[str]] = [[] for _ in requests]
        for owner, text in zip(owners, translated, strict=True):
            joined[owner].append(_from_html(text))
        return [" ".join(parts) if parts else None for parts in joined]

    def _translate_fragments(self, text: str, source: str, target: str) -> str:
        """Translate only the text between placeholders and tags."""
        parts = _MARKUP.split(text)
        slots = [
            index for index in range(0, len(parts), 2) if _LETTER.search(parts[index])
        ]  # even indexes are plain text
        plain = [html.escape(parts[index].strip(), quote=False) for index in slots]
        for index, result in zip(slots, self._translate_all(plain, source, target), strict=True):
            part = parts[index]
            lead = part[: len(part) - len(part.lstrip())]
            trail = part[len(part.rstrip()) :]
            parts[index] = f"{lead}{html.unescape(result).strip()}{trail}"
        return "".join(parts)

    @staticmethod
    def _translate_all(texts: list[str], source: str, target: str) -> list[str]:
        if not texts:
            return []
        try:
            return translate_html(texts, source, target)
        except Refused as refused:
            log.info("translateHtml unavailable (%s); trying the single-text endpoint", refused)
            try:
                return [translate_text(html.unescape(text), source, target) for text in texts]
            except Refused as exc:
                raise TransientTranslationError(f"Google Translate unavailable: {exc}") from exc


def _to_html(text: str) -> str:
    """Escape the text between markup so ``<`` or ``&`` in the prose survive as text."""
    parts = _MARKUP.split(text)
    for index in range(0, len(parts), 2):
        parts[index] = html.escape(parts[index], quote=False)
    return "".join(parts)


def _from_html(text: str) -> str:
    text = _SPACE_AFTER_CLOSE.sub(r"\1", text)
    text = _SPACE_INSIDE_OPEN.sub(r" \1", text)
    text = _SPACE_INSIDE_CLOSE.sub(r"\1 ", text)
    return _SPACES.sub(" ", html.unescape(text)).strip()


def _chunks(text: str) -> list[str]:
    if len(text) <= _MAX_CHARS:
        return [text]
    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > _MAX_CHARS:  # a single enormous "sentence"
            chunks.append(sentence[:_MAX_CHARS])
            sentence = sentence[_MAX_CHARS:]
        if current and len(current) + 1 + len(sentence) > _MAX_CHARS:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current:
        chunks.append(current)
    return chunks
