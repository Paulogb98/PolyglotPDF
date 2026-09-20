"""Prompts of the reading companion: system prompt, quick actions and user turns."""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import ConfigError
from ..reading.context import PassageContext
from ..translation.languages import display_name

PROMPT_VERSION = "2"


@dataclass(frozen=True, slots=True)
class Action:
    key: str
    label: str  # shown in the interface (Portuguese)
    instruction: str  # given to the model


_ACTIONS = (
    Action("ask", "Perguntar", "Answer the reader's question about the passage."),
    Action(
        "explain",
        "Explicar",
        "Explain what the selected passage says and means in context: the idea, how it "
        "follows from what came before and why it matters.",
    ),
    Action(
        "simplify",
        "Explicar de forma simples",
        "Explain the passage in plain words, for an intelligent reader without background "
        "in the field; use a short example or analogy when it helps.",
    ),
    Action(
        "context",
        "Contexto",
        "Give the context needed to understand the passage: its place in the argument or "
        "narrative and the historical, cultural, biographical or scientific background, "
        "allusions and references it relies on.",
    ),
    Action(
        "concepts",
        "Conceitos e fórmulas",
        "Explain the technical terms, concepts, notation and formulas in the passage step "
        "by step: what each symbol means and what each formula expresses.",
    ),
    Action(
        "vocabulary",
        "Vocabulário",
        "Explain the difficult, archaic, technical or figurative words and expressions of "
        "the passage, each with its meaning in this context.",
    ),
    Action("summarize", "Resumir", "Summarize the passage and its main point in a few sentences."),
    Action(
        "translate",
        "Traduzir",
        "Translate the selected passage faithfully, keeping meaning, tone and register; "
        "then add brief notes only for terms that are hard to translate.",
    ),
    Action(
        "comment",
        "Comentar",
        "Comment on the passage: its significance, strengths, weaknesses or open questions, "
        "and how it connects to the rest of the work.",
    ),
)
ACTIONS: dict[str, Action] = {action.key: action for action in _ACTIONS}


def list_actions() -> list[Action]:
    return list(_ACTIONS)


def system_prompt(language: str) -> str:
    return f"""You are a reading companion built into a PDF and e-book reader. The reader selected \
a passage of the document (or is looking at a page) and wants help with it.

Always answer in {display_name(language)}, whatever the language of the document. When you \
discuss specific words of the text, quote them in the original.

How to help:
- Stay focused on the selected passage. Use the surrounding context (text before, current \
paragraph, text after) and the section to interpret it precisely.
- Adapt to the kind of text. Scientific and technical texts: explain concepts, notation, \
equations, methods, assumptions and how the passage fits the argument. Literature, classics \
and demanding books: explain vocabulary, archaic or figurative language, historical and \
cultural context, allusions and the passage's role in the work.
- You may use general knowledge about the work, its author and its field. Make clear what \
comes from the text and what is background knowledge, and say so when you are unsure. Never \
invent quotations, page numbers or references.
- The context marks where pages begin with [p. N]. When you refer to another place in the \
book ("two pages back he prepares this"), give its page as (p. N) with a number taken from \
those markers or from the Page line: the reader can click it to go there. Never give a page \
you were not shown.
- Avoid spoilers: do not reveal what happens or is concluded later in the work, beyond the \
context provided, unless the reader explicitly asks.
- The text was extracted from a PDF: line breaks, hyphenation and mathematical symbols may be \
imperfect. Reconstruct formulas sensibly and write mathematics in LaTeX, between $...$ inline \
or $$...$$ for displayed equations.
- Be clear and concise: lead with the direct answer, then add detail. Use Markdown (short \
paragraphs, lists, bold for key terms). No preamble."""


def context_message(context: PassageContext, action: str, question: str | None) -> str:
    """First user turn: the passage, its context, the task and the question."""
    task = _task(action, question)
    location = [f"Title: {context.title}"]
    if context.authors:
        location.append(f"Authors: {context.authors}")
    if context.section:
        location.append("Section: " + " › ".join(context.section))
    page = f"Page: p. {context.page + 1} of {context.page_count}"
    if context.page_label != str(context.page + 1):
        page += f" (printed as {context.page_label!r})"
    location.append(page)
    parts = ["<document>\n" + "\n".join(location) + "\n</document>"]
    if context.before:
        parts.append(f"<context_before>\n{context.before}\n</context_before>")
    if context.whole_page:
        parts.append(f"<page_text>\n{context.current}\n</page_text>")
        task = "The reader is looking at this page (no passage selected).\n" + task
    else:
        parts.append(f"<current_paragraph>\n{context.current}\n</current_paragraph>")
        parts.append(f"<selected_passage>\n{context.selection}\n</selected_passage>")
    if context.after:
        parts.append(f"<context_after>\n{context.after}\n</context_after>")
    parts.append(task)
    return "\n\n".join(parts)


def follow_up_message(action: str, question: str | None) -> str:
    """Later user turns: the passage and its context are already in the conversation."""
    return _task(action, question)


def _task(action: str, question: str | None) -> str:
    chosen = ACTIONS.get(action)
    if chosen is None:
        raise ConfigError(f"Unknown action {action!r}; choose one of {', '.join(ACTIONS)}")
    question = (question or "").strip()
    if chosen.key == "ask" and not question:
        raise ConfigError("Write a question for the companion")
    lines = [f"Task: {chosen.instruction}"]
    if question:
        lines.append(f"Reader's question: {question}")
    return "\n".join(lines)
