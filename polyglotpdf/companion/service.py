"""High-level reading companion: turns a passage and a request into a streamed answer."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from ..reading.context import PassageContext
from .chat import ChatClient, ChatMessage
from .prompts import context_message, follow_up_message, system_prompt


class ReadingCompanion:
    """Answers questions about passages of a document with a chat model.

    Typical use::

        context = build_context(index, Anchor(12, 340), Anchor(12, 512))
        companion = ReadingCompanion(create_chat_client("anthropic"), language="pt-BR")
        for piece in companion.ask(context, "explain"):
            print(piece, end="")

    Follow-up questions pass the previous turns as ``history``; the passage and its
    context travel only in the first turn.
    """

    def __init__(self, client: ChatClient, *, language: str = "pt-BR") -> None:
        self.client = client
        self.language = language

    def message(
        self, context: PassageContext | None, action: str = "ask", question: str | None = None
    ) -> ChatMessage:
        """The user turn for ``action`` (with the passage and its context when given)."""
        if context is None:
            return ChatMessage("user", follow_up_message(action, question))
        return ChatMessage("user", context_message(context, action, question))

    def stream(self, history: Sequence[ChatMessage], message: ChatMessage) -> Iterator[str]:
        """Send ``message`` after ``history`` and yield the answer in pieces."""
        return self.client.stream(system_prompt(self.language), [*history, message])

    def ask(
        self,
        context: PassageContext,
        action: str = "ask",
        question: str | None = None,
        history: Sequence[ChatMessage] = (),
    ) -> Iterator[str]:
        message = self.message(None if history else context, action, question)
        return self.stream(history, message)
