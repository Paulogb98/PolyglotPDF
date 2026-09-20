"""The tutor: it plans a reading session and closes it with questions.

The companion answers when called; the tutor conducts a session — it says what to
expect, marks the passages where the text tightens, keeps a small map of the concepts
in play and, at the end, asks three questions. Both talk to the same chat client; the
difference is only in the prompt and in the shape of the answer, which here is JSON so
the interface can lay it out (see :mod:`polyglotpdf.app.sessions`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from ..errors import ReplyFormatError
from ..translation.languages import display_name
from .chat import ChatClient, ChatMessage

PLAN_VERSION = "2"
_MAX_DENSE = 4
_MAX_QUESTIONS = 3
_MAX_CONCEPTS = 6
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def system_prompt(language: str) -> str:
    return f"""You are the tutor of a reading application. You lead a reader through one \
session of a demanding book: a stretch of pages read in one sitting.

Always write in {display_name(language)}, whatever the language of the book. Quote the \
book's own words in the original when you point at a passage.

Answer with a single JSON object and nothing else — no prose around it, no code fence. \
Shape:

{{
  "intro": "2 to 3 sentences: what this stretch argues and why it is hard. No spoilers \
beyond these pages.",
  "expect": ["3 short lines telling the reader what you will do in this session"],
  "concepts": [
    {{"name": "a concept in play, one to three words, lower case, in \
{display_name(language)}",
      "term": "the same concept exactly as the text given to you writes it, in the \
text's own language (it is searched for in the book)",
      "definition": "one sentence: what it means in this book"}}
  ],
  "dense": [
    {{"quote": "the exact sentence from the text where it tightens (verbatim, short)",
      "why": "one sentence: what makes it hard",
      "explain": "2 to 4 sentences explaining it",
      "question": "one question that checks the reader got it",
      "paraphrase": "the same idea in plain words, 1 to 2 sentences"}}
  ],
  "questions": [
    {{"text": "a question about this stretch, answerable from it",
      "answer": "the answer you would accept, 2 to 4 sentences",
      "hint": "one short nudge"}}
  ]
}}

Rules: at most {_MAX_CONCEPTS} entries in "concepts", at most {_MAX_DENSE} in "dense" \
and exactly {_MAX_QUESTIONS} in "questions". A concept the reader already met in an \
earlier session keeps the name it had there. Every "quote" must appear verbatim in the \
text given to you. Never invent page numbers or references. Mathematics in LaTeX between \
$...$."""


def plan_message(
    *,
    title: str,
    authors: str | None,
    session_title: str,
    number: int,
    total: int,
    first_label: str,
    last_label: str,
    text: str,
    known: Sequence[str] = (),
) -> ChatMessage:
    head = [f"Book: {title}"]
    if authors:
        head.append(f"Authors: {authors}")
    head.append(f"Session {number} of {total}: {session_title}")
    head.append(f"Pages {first_label} to {last_label}")
    if known:
        head.append("Concepts met in earlier sessions: " + "; ".join(known))
    return ChatMessage(
        "user",
        "<session>\n" + "\n".join(head) + "\n</session>\n\n"
        f"<text>\n{text}\n</text>\n\n"
        "Plan this session as the JSON object described in your instructions.",
    )


def plan(client: ChatClient, language: str, message: ChatMessage) -> dict[str, Any]:
    """Run one tutor turn and parse the plan it answers with."""
    pieces: list[str] = []
    stream = client.stream(system_prompt(language), [message])
    try:
        pieces.extend(stream)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    return parse_plan("".join(pieces))


def check_system_prompt(language: str) -> str:
    return f"""You are the tutor of a reading application. At the end of a session the \
reader answered one of your questions in their own words; comment on the answer.

Write in {display_name(language)}, 2 to 4 sentences, plain prose (Markdown emphasis at \
most). Say what the answer gets right, then what the text says that the answer misses \
or bends; point at the book's own words when it helps. No grade, no score, no praise \
formulas. If the answer is empty or off-topic, say so kindly and give a first step."""


def check_message(*, question: str, expected: str, answer: str, passage: str) -> ChatMessage:
    return ChatMessage(
        "user",
        f"<question>\n{question}\n</question>\n\n"
        f"<what_the_text_supports>\n{expected}\n</what_the_text_supports>\n\n"
        f"<passage>\n{passage}\n</passage>\n\n"
        f"<reader_answer>\n{answer}\n</reader_answer>\n\n"
        "Comment on the reader's answer as described in your instructions.",
    )


def check(client: ChatClient, language: str, message: ChatMessage) -> str:
    """The tutor's comment on one answer, as plain text."""
    pieces: list[str] = []
    stream = client.stream(check_system_prompt(language), [message])
    try:
        pieces.extend(stream)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    return "".join(pieces).strip()


def parse_plan(answer: str) -> dict[str, Any]:
    """Read the tutor's JSON, tolerating a code fence or text around it."""
    text = _FENCE.sub("", answer).strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # The reader gets the plain sentence; the parser's complaint stays in the log.
        raise ReplyFormatError("tutor") from exc
    if not isinstance(data, dict):
        raise ReplyFormatError("tutor")
    return {
        "version": PLAN_VERSION,
        "intro": str(data.get("intro") or "").strip(),
        "expect": _lines(data.get("expect"), 3),
        "concepts": plan_concepts(data.get("concepts")),
        "dense": _dense(data.get("dense")),
        "questions": _questions(data.get("questions")),
    }


def plan_concepts(value: Any) -> list[dict[str, str]]:
    """The plan's concepts as ``{name, term, definition}``.

    Plans of the first version listed bare names; they read as concepts without a term
    or a definition.
    """
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    concepts: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            term = str(item.get("term") or "").strip()
            definition = str(item.get("definition") or "").strip()
        else:
            name, term, definition = str(item).strip(), "", ""
        name = name or term
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        concepts.append({"name": name, "term": term, "definition": definition})
    return concepts[:_MAX_CONCEPTS]


def upgrade_plan(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """A stored plan in the current shape (concepts as objects)."""
    if plan is None:
        return None
    return {**plan, "concepts": plan_concepts(plan.get("concepts"))}


def _lines(value: Any, limit: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


def _dense(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    entries = []
    for item in value[:_MAX_DENSE]:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or "").strip()
        if not quote:
            continue
        entries.append(
            {
                "quote": quote,
                "why": str(item.get("why") or "").strip(),
                "explain": str(item.get("explain") or "").strip(),
                "question": str(item.get("question") or "").strip(),
                "paraphrase": str(item.get("paraphrase") or "").strip(),
            }
        )
    return entries


def _questions(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    entries = []
    for item in value[:_MAX_QUESTIONS]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        entries.append(
            {
                "text": text,
                "answer": str(item.get("answer") or "").strip(),
                "hint": str(item.get("hint") or "").strip(),
            }
        )
    return entries


__all__ = [
    "PLAN_VERSION",
    "check",
    "check_message",
    "check_system_prompt",
    "parse_plan",
    "plan",
    "plan_concepts",
    "plan_message",
    "system_prompt",
    "upgrade_plan",
]
