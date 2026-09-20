"""What the application writes for people, in the interface's language.

The interface sends its language with every request (``X-PolyglotPDF-Language``); an async
dependency puts it in a context variable, which the request's thread inherits, so ``msg()``
anywhere under a request answers in that language. Work that outlives the request (a
translation job) takes the language when it starts and uses it when it ends.

Only text meant for the reader lives here. Technical errors (a provider's own message, a
validation detail) stay as they are.
"""

from __future__ import annotations

from contextvars import ContextVar

from fastapi import Request

from ..translation.engines import EngineInfo

HEADER = "x-polyglotpdf-language"
LANGS = ("pt-BR", "en")
DEFAULT = "pt-BR"

_current: ContextVar[str] = ContextVar("polyglotpdf_language", default=DEFAULT)


def normalize(value: str | None) -> str:
    """Any English is English; everything else is the interface's first language."""
    return "en" if (value or "").strip().lower().startswith("en") else DEFAULT


def language() -> str:
    return _current.get()


def use_language(value: str | None) -> None:
    _current.set(normalize(value))


async def request_language(request: Request) -> None:
    """Dependency of every route: the language the interface is speaking."""
    use_language(request.headers.get(HEADER))


_MESSAGES: dict[str, tuple[str, str]] = {
    "key.needed": (
        "{engine} precisa de uma chave de API: cadastre-a em Ajustes",
        "{engine} needs an API key: add it in Settings",
    ),
    "companion.noEngine": (
        "O companheiro de leitura precisa de um motor de IA: cadastre uma chave em Ajustes",
        "The reading companion needs an AI engine: add an API key in Settings",
    ),
    "ask.nothingSelected": (
        "Selecione um trecho ou uma página para perguntar",
        "Select a passage or a page to ask about",
    ),
    "ask.noQuestion": (
        "Escreva uma pergunta para o companheiro",
        "Write a question for the companion",
    ),
    "reply.tutor": (
        "O tutor respondeu fora do formato esperado. Tente de novo.",
        "The tutor answered in an unexpected format. Try again.",
    ),
    "reply.dictionary": (
        "O dicionário respondeu fora do formato esperado. Tente de novo.",
        "The dictionary answered in an unexpected format. Try again.",
    ),
    "nothing.throttled": (
        "o {engine} recusou os pedidos desta conexão por excesso de uso",
        "{engine} turned this connection’s requests down for overuse",
    ),
    "nothing.offline": (
        "não deu para falar com o {engine} (sem conexão?)",
        "couldn’t reach {engine} (no connection?)",
    ),
    "nothing.silent": ("o {engine} não respondeu", "{engine} didn’t answer"),
    "nothing.translated": (
        "Nada foi traduzido: {why}. O livro continua no original. "
        "Tente de novo em alguns minutos ou escolha outro motor.",
        "Nothing was translated: {why}. The book is still in the original. "
        "Try again in a few minutes or choose another engine.",
    ),
    "due.minutes": ("em {n} min", "in {n} min"),
    "due.tomorrow": ("amanhã", "tomorrow"),
    "due.days": ("em {n} dias", "in {n} days"),
    "due.month": ("em 1 mês", "in 1 month"),
    "due.months": ("em {n} meses", "in {n} months"),
    "session.beginning": ("Início", "Beginning"),
    "session.reading": ("Leitura", "Reading"),
    "thread.page": ("Página {page}", "Page {page}"),
    "secrets.memory": ("memória (testes)", "memory (tests)"),
    "secrets.file": (
        "arquivo local (sem cofre do sistema disponível)",
        "local file (no system credential store available)",
    ),
    "secrets.windows": ("Gerenciador de Credenciais do Windows", "Windows Credential Manager"),
    "secrets.macos": ("Keychain do macOS", "macOS Keychain"),
    "secrets.linux": ("cofre do sistema (Secret Service)", "system keyring (Secret Service)"),
    "secrets.other": ("cofre do sistema ({name})", "system credential store ({name})"),
}

#: The engines' names and one-line descriptions in Portuguese; the catalogue's own are English.
_ENGINES_PT: dict[str, tuple[str, str]] = {
    "google": (
        "Google Tradutor",
        "Tradução gratuita pelo endpoint web do Google, sem chave de API.",
    ),
    "deepl": ("DeepL", "Tradução neural da DeepL (planos Free e Pro)."),
    "anthropic": (
        "Anthropic Claude",
        "Modelos Claude, com saída estruturada e cache de prompt.",
    ),
    "openai": ("OpenAI", "Modelos GPT pela Responses API."),
    "deepseek": ("DeepSeek", "Modelos DeepSeek (API compatível com OpenAI)."),
    "gemini": ("Google Gemini", "Modelos Gemini pelo endpoint compatível com OpenAI."),
    "mistral": ("Mistral AI", "Modelos Mistral (API compatível com OpenAI)."),
    "xai": ("xAI Grok", "Modelos Grok (API compatível com OpenAI)."),
    "qwen": ("Alibaba Qwen", "Modelos Qwen pelo Model Studio (modo compatível com OpenAI)."),
    "openrouter": ("OpenRouter", "Centenas de modelos de vários provedores com uma única chave."),
    "ollama": ("Ollama (local)", "Modelos abertos rodando no próprio computador, sem chave."),
    "openai-compatible": (
        "Outro provedor compatível com OpenAI",
        "Qualquer servidor Chat Completions: informe base_url, modelo e chave.",
    ),
    "pseudo": (
        "Pseudo-tradução",
        "Acentua e alonga o texto (~30%) para testar o layout sem custo.",
    ),
    "echo": (
        "Eco",
        "Testes sem rede: na tradução recompõe o texto original; no companheiro de leitura "
        "mostra o contexto que seria enviado à IA.",
    ),
}


def msg(key: str, lang: str | None = None, **values: object) -> str:
    """The message ``key`` in ``lang`` (default: the current request's), filled in."""
    pt, en = _MESSAGES[key]
    text = en if normalize(lang or language()) == "en" else pt
    return text.format(**values) if values else text


def engine_text(info: EngineInfo) -> tuple[str, str]:
    """An engine's label and description in the current language."""
    if language() != "en" and info.name in _ENGINES_PT:
        return _ENGINES_PT[info.name]
    return info.label, info.description
