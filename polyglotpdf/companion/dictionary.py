"""The dictionary entry shown when the reader taps a word twice.

Two senses of the same word: the common one, and the one it carries *in this book* —
which for a demanding work is usually the one that matters. The entry is asked of the
chat model as JSON so the panel can lay it out, and the number of uses comes from the
document itself, not from the model.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..errors import ReplyFormatError
from ..translation.languages import display_name
from .chat import ChatClient, ChatMessage

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)
_MAX_SENSES = 3


def system_prompt(language: str) -> str:
    return f"""You write dictionary entries for a reading application. The reader tapped a \
word in a book and wants to know what it means there.

Write in {display_name(language)}. Keep the headword in the language of the book.

Answer with a single JSON object and nothing else — no prose, no code fence:

{{
  "word": "the headword as it is written in the book, lemmatised if inflected",
  "pronunciation": "IPA between brackets, or an empty string when you are not sure",
  "grammar": "part of speech and the grammatical detail that matters, a few words",
  "senses": [{{"gloss": "the meaning, one sentence", "common": true}}],
  "in_book": "2 to 3 sentences: the sense the word carries in THIS work, and whether it \
is a technical term for this author",
  "related": ["up to 3 words of the same family or contrast, in the book's language"]
}}

At most {_MAX_SENSES} senses, the common one first ("common": true), the technical one \
last ("common": false). Never invent an etymology or a citation."""


def entry_message(
    *,
    word: str,
    title: str,
    authors: str | None,
    language: str | None,
    sentence: str,
    context: str,
    uses: int,
) -> ChatMessage:
    head = [f"Word: {word}", f"Book: {title}"]
    if authors:
        head.append(f"Authors: {authors}")
    if language:
        head.append(f"Language of the book: {language}")
    head.append(f"Uses of the word found so far in the book: {uses}")
    return ChatMessage(
        "user",
        "<lookup>\n" + "\n".join(head) + "\n</lookup>\n\n"
        f"<sentence>\n{sentence}\n</sentence>\n\n"
        f"<context>\n{context}\n</context>\n\n"
        "Write the entry as the JSON object described in your instructions.",
    )


def lookup(client: ChatClient, language: str, message: ChatMessage) -> dict[str, Any]:
    pieces: list[str] = []
    stream = client.stream(system_prompt(language), [message])
    try:
        pieces.extend(stream)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    return parse_entry("".join(pieces))


def parse_entry(answer: str) -> dict[str, Any]:
    text = _FENCE.sub("", answer).strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # The reader gets the plain sentence; the parser's complaint stays in the log.
        raise ReplyFormatError("dictionary") from exc
    if not isinstance(data, dict):
        raise ReplyFormatError("dictionary")
    senses = []
    raw = data.get("senses")
    if isinstance(raw, list):
        for item in raw[:_MAX_SENSES]:
            if isinstance(item, dict) and str(item.get("gloss") or "").strip():
                senses.append(
                    {"gloss": str(item["gloss"]).strip(), "common": bool(item.get("common", True))}
                )
    related = data.get("related")
    return {
        "word": str(data.get("word") or "").strip(),
        "pronunciation": str(data.get("pronunciation") or "").strip(),
        "grammar": str(data.get("grammar") or "").strip(),
        "senses": senses,
        "in_book": str(data.get("in_book") or "").strip(),
        "related": [str(item).strip() for item in related[:3] if str(item).strip()]
        if isinstance(related, list)
        else [],
    }


__all__ = ["entry_message", "lookup", "parse_entry", "system_prompt"]
