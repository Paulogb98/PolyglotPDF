"""Reading companion: an AI that answers questions about a selected passage.

The companion talks to the same providers as the AI translation engines (the ones
with ``supports_chat`` in the catalogue). It receives the passage together with its
context — document title, authors, section, the paragraph it belongs to and the text
before and after it (see :mod:`polyglotpdf.reading.context`) — so it can explain,
give background, clarify vocabulary or formulas, summarise or translate precisely
that part of the work.
"""

from .chat import (
    AnthropicChat,
    ChatClient,
    ChatCompletionsChat,
    ChatMessage,
    EchoChat,
    OpenAIChat,
    create_chat_client,
)
from .prompts import ACTIONS, PROMPT_VERSION, Action, list_actions
from .service import ReadingCompanion

__all__ = [
    "ACTIONS",
    "PROMPT_VERSION",
    "Action",
    "AnthropicChat",
    "ChatClient",
    "ChatCompletionsChat",
    "ChatMessage",
    "EchoChat",
    "OpenAIChat",
    "ReadingCompanion",
    "create_chat_client",
    "list_actions",
]
