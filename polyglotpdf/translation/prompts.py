"""Prompts shared by every engine driven by a large language model.

The system prompt only depends on the language pair, the glossary and the
document title, so it is identical for every request of a document and can be
served from the providers' prompt caches.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from .base import TranslationContext, TranslationRequest
from .languages import display_name

PROMPT_VERSION = "4"

_SYSTEM_TEMPLATE = """\
You are an expert translator of scientific papers and books. Translate the text segments you \
receive from {source} into {target}.

## Input
The user message contains a JSON array of segments extracted from a document, in reading order. \
Each segment has an "id", a "role" (paragraph, heading, caption, footnote, table cell, \
reference...) and the "text". Paragraphs are complete, even when the original splits them across \
columns or pages. Translate every segment completely, using the neighbouring segments as context \
for meaning and terminology.

## Markup
- Placeholders such as {{v1}} or {{v12}} stand for mathematical formulas, symbols or note markers \
that are drawn separately. Copy every placeholder of a segment exactly once and unchanged, in the \
position where it belongs in the translated sentence.
- <b>…</b>, <i>…</i> and <c>…</c> mark bold, italic and monospaced text. Keep each pair around \
the words that correspond to the original ones.

## Style
- Write fluent, idiomatic {target} with the register of the original: precise academic prose for \
papers, literary prose for books.
- Use the established terminology of the field in {target}.
- Headings stay concise, like headings.
- Output only the translation, without explanations or notes.
{extra}
## Output
Return JSON of the form {{"translations": [{{"id": "...", "text": "..."}}]}} with exactly one \
entry for every input id."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}


def build_system_prompt(context: TranslationContext) -> str:
    extra: list[str] = []
    if context.document_title:
        extra.append(
            f'\n## Document\nThe document is titled "{context.document_title}". Use it as '
            "context only."
        )
    if not context.glossary.is_empty:
        extra.append(f"\n## Glossary\n{context.glossary.to_prompt()}")
    return _SYSTEM_TEMPLATE.format(
        source=display_name(context.source_lang),
        target=display_name(context.target_lang),
        extra="\n".join(extra) + ("\n" if extra else ""),
    )


def build_user_message(requests: Sequence[TranslationRequest], *, strict: bool = False) -> str:
    payload = [{"id": r.uid, "role": r.role, "text": r.text} for r in requests]
    message = "Translate these segments:\n" + json.dumps(payload, ensure_ascii=False)
    if strict:
        message += (
            "\n\nA previous attempt lost or altered placeholders. Every {vN} placeholder of a "
            "segment must appear exactly once in its translation."
        )
    return message
