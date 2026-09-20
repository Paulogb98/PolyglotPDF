"""Application state and the operations the API routes are built on."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast

from fastapi import Request

from ..companion import ACTIONS, ChatClient, EchoChat, ReadingCompanion, create_chat_client
from ..companion import dictionary as dictionary_prompts
from ..companion import tutor as tutor_prompts
from ..companion.prompts import follow_up_message
from ..config import Settings
from ..errors import ConfigError, TranslationError
from ..pdf.loader import parse_page_range
from ..reading.context import Anchor, build_context
from ..translation.engines import EngineInfo, EngineKind, chat_engines, get_engine, list_engines
from .config import AppConfig
from .conversations import Conversations, Thread
from .db import Database
from .documents import DocumentRegistry
from .i18n import engine_text, language, msg
from .jobs import Job, JobManager
from .library import Library
from .preferences import PreferencesStore
from .schemas import AskRequest, TranslateRequest
from .secrets import SecretStore, default_store
from .sessions import (
    Session,
    Sessions,
    concept_history,
    known_before,
    pace,
    session_text,
)
from .study import Study

#: Concepts on the map at the end of a session, and how many of the next ones it shows.
_MAP_SIZE = 18
_MAP_AHEAD = 3


@dataclass(slots=True)
class PreparedQuestion:
    thread: Thread
    stream: Iterator[str]
    client: ChatClient
    action: str


class AppState:
    def __init__(self, config: AppConfig, *, secrets: SecretStore | None = None) -> None:
        data = config.data_dir
        data.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.db = Database(data / "library.sqlite3")
        self.library = Library(self.db, data / "documents")
        self.conversations = Conversations(self.db)
        self.registry = DocumentRegistry(self.library)
        self.jobs = JobManager(isolation=config.job_isolation)
        self.secrets = secrets or default_store(data)
        self.preferences = PreferencesStore(data / "preferences.json")
        self.study = Study(self.db)
        self.sessions = Sessions(self.db)
        self._dictionary: dict[tuple[str, str], dict[str, Any]] = {}

    def close(self) -> None:
        self.jobs.shutdown()
        self.registry.close_all()
        self.db.close()

    # ------------------------------------------------------------------ keys and engines
    def api_key(self, engine: str) -> str | None:
        """The key stored in the application, else the provider's environment variable."""
        info = get_engine(engine)
        return self.secrets.get(info.name) or info.api_key()

    def key_source(self, engine: str) -> str | None:
        info = get_engine(engine)
        if self.secrets.get(info.name):
            return "app"
        return "env" if info.api_key() else None

    def ready(self, info: EngineInfo) -> bool:
        return not info.requires_key or self.key_source(info.name) is not None

    def engine_view(self, engine: str) -> dict[str, Any]:
        info = get_engine(engine)
        prefs = self.preferences.get().engine(info.name)
        label, description = engine_text(info)
        return {
            "name": info.name,
            "label": label,
            "kind": info.kind.value,
            "description": description,
            "website": info.website,
            "requires_key": info.requires_key,
            "key_env": list(info.key_env),
            "key_source": self.key_source(info.name),
            "key_hint": _hint(self.api_key(info.name)) if info.requires_key else None,
            "ready": self.ready(info),
            "default_model": info.default_model,
            "model": prefs.model,
            "default_base_url": info.base_url,
            "base_url": prefs.base_url,
            "lists_models": info.lists_models,
            "supports_glossary": info.supports_glossary,
            "supports_chat": info.supports_chat,
        }

    def engines_view(self) -> list[dict[str, Any]]:
        return [self.engine_view(info.name) for info in list_engines()]

    def companion_engine(self) -> str | None:
        """The chosen companion engine, or the first AI engine with a key."""
        chosen = self.preferences.get().companion_engine
        if chosen:
            return chosen
        for info in chat_engines():
            if info.kind is EngineKind.AI and info.requires_key and self.ready(info):
                return info.name
        return None

    def chat_client(self) -> ChatClient:
        engine = self.companion_engine()
        if engine is None:
            raise ConfigError(msg("companion.noEngine"))
        info = get_engine(engine)
        if info.name == "echo":
            return EchoChat(delay=self.config.echo_delay)
        if info.requires_key and not self.api_key(info.name) and info.name != "anthropic":
            raise ConfigError(msg("key.needed", engine=engine_text(info)[0]))
        prefs = self.preferences.get()
        engine_prefs = prefs.engine(info.name)
        return create_chat_client(
            info.name,
            model=engine_prefs.model,
            api_key=self.api_key(info.name),
            base_url=engine_prefs.base_url,
            effort=prefs.companion_effort,
        )

    # ------------------------------------------------------------------ jobs
    def start_translation(self, document_id: str, request: TranslateRequest) -> Job:
        document = self.library.get(document_id)
        info = get_engine(request.engine)
        engine_prefs = self.preferences.get().engine(info.name)
        settings = Settings()
        translation = settings.translation
        translation.engine = info.name
        translation.model = request.model or engine_prefs.model
        translation.base_url = engine_prefs.base_url
        translation.source_lang = request.source_lang
        translation.target_lang = request.target_lang
        translation.cache_path = self.config.data_dir / "cache" / "translations.sqlite3"
        settings.content.translate_code = request.translate_code
        settings.pages = (request.pages or "").strip() or None
        settings.output.keep_all_pages = True  # the translation lines up with the original
        settings.validate()
        pages = parse_page_range(settings.pages, document.pages)
        key = self.api_key(info.name)
        if info.requires_key and not key and info.name != "anthropic":
            raise ConfigError(msg("key.needed", engine=engine_text(info)[0]))

        version_id, output = self.library.new_version(document_id)
        payload = {
            "settings": settings.to_dict(),
            "api_key": key,
            "input": str(self.library.reading_path(document_id)),
            "output": str(output),
        }
        params = {
            "title": document.title,
            "engine": info.name,
            "engine_label": engine_text(info)[0],
            "model": translation.model or info.default_model,
            "source_lang": translation.source_lang,
            "target_lang": translation.target_lang,
            "pages": settings.pages,
        }

        # The job ends after the request: it keeps the language the reader asked in.
        asked_in = language()
        label = engine_text(info)[0]

        def on_done(job: Job) -> None:
            report = job.result or {}
            if report.get("failed") and not report.get("translated"):
                output.unlink(missing_ok=True)  # a copy of the original is not a translation
                raise TranslationError(nothing_translated(label, report, asked_in))
            self.library.add_version(
                document_id,
                version_id,
                target_lang=translation.target_lang,
                engine=str(report.get("engine") or info.name),
                pages=pages if settings.pages else None,
                report=report,
            )
            job.version_id = version_id

        return self.jobs.submit("translate", document_id, params, payload, on_done)

    def start_estimate(self, document_id: str, pages: str | None) -> Job:
        document = self.library.get(document_id)
        settings = Settings()
        settings.pages = (pages or "").strip() or None
        parse_page_range(settings.pages, document.pages)
        payload = {
            "settings": settings.to_dict(),
            "input": str(self.library.reading_path(document_id)),
        }
        params = {"title": document.title, "pages": settings.pages}
        return self.jobs.submit("estimate", document_id, params, payload)

    # ------------------------------------------------------------------ companion
    def prepare_question(self, body: AskRequest) -> PreparedQuestion:
        """Create or continue a conversation and start the model's answer (lazily)."""
        if body.action == "ask" and not (body.question or "").strip():
            raise ConfigError(msg("ask.noQuestion"))
        follow_up_message(body.action, body.question)  # validates the action and question
        client = self.chat_client()
        prefs = self.preferences.get()
        companion = ReadingCompanion(client, language=prefs.companion_language)
        if body.thread_id:
            thread = self.conversations.get(body.thread_id)
            history = self.conversations.history(thread.id)
            message = companion.message(
                None if history else thread.context, body.action, body.question
            )
        else:
            if body.start is None:
                raise ConfigError(msg("ask.nothingSelected"))
            index = self.registry.get(body.document_id, body.version_id)
            start = Anchor(body.start.page, body.start.offset)
            end = Anchor(body.end.page, body.end.offset) if body.end else None
            context = build_context(index, start, end, size=prefs.context_size)
            thread = self.conversations.create(body.document_id, body.version_id, context)
            history = []
            message = companion.message(context, body.action, body.question)
        display = (body.question or "").strip() or ACTIONS[body.action].label
        self.conversations.add_message(
            thread.id,
            "user",
            message.content,
            display,
            action=body.action,
            engine=client.name,
            model=client.model,
        )
        return PreparedQuestion(
            thread=self.conversations.get(thread.id),
            stream=companion.stream(history, message),
            client=client,
            action=body.action,
        )

    # ------------------------------------------------------------------ study and tutor
    def section_at(
        self, document_id: str, version_id: str | None, page: int, offset: int
    ) -> tuple[str, ...]:
        """The chapter a passage belongs to, used to file marks in the notebook."""
        try:
            return self.registry.get(document_id, version_id).section_at(page, offset)
        except (LookupError, OSError):
            return ()

    def sessions_of(self, document_id: str, version_id: str | None = None) -> list[Session]:
        index = self.registry.get(document_id, version_id)
        return self.sessions.ensure(document_id, index)

    def plan_session(
        self, document_id: str, number: int, version_id: str | None = None, *, refresh: bool = False
    ) -> Session:
        """Ask the tutor to plan a session (once), and mark its dense passages."""
        sessions = self.sessions_of(document_id, version_id)
        session = self.sessions.get(document_id, number)
        if session.plan is not None and not refresh:
            return session
        document = self.library.get(document_id)
        index = self.registry.get(document_id, version_id)
        total = len(sessions)
        message = tutor_prompts.plan_message(
            title=document.title,
            authors=document.authors,
            session_title=session.title,
            number=session.number,
            total=total,
            first_label=index.page_label(session.start_page),
            last_label=index.page_label(min(session.end_page, index.page_count - 1)),
            text=session_text(index, session),
            known=known_before(sessions, number),
        )
        client = self.chat_client()
        try:
            plan = tutor_prompts.plan(client, self.preferences.get().companion_language, message)
        finally:
            client.close()
        planned = self.sessions.save_plan(document_id, number, plan)
        self._mark_dense(document_id, version_id, planned)
        return planned

    def _mark_dense(self, document_id: str, version_id: str | None, session: Session) -> None:
        """Put the tutor's dense passages on the page, where it found them."""
        plan = session.plan or {}
        existing = {mark.quote for mark in self.study.marks(document_id, kind="tutor")}
        index = self.registry.get(document_id, version_id)
        for entry in plan.get("dense", []):
            quote = str(entry.get("quote") or "").strip()
            if not quote or quote in existing:
                continue
            found = self._find_quote(index, session, quote)
            if found is None:
                continue
            page, start, end = found
            self.study.add_mark(
                document_id,
                version_id=version_id,
                kind="note",
                color="green",
                quote=quote,
                note=str(entry.get("why") or entry.get("explain") or "").strip() or None,
                tags=[],
                start_page=page,
                start_offset=start,
                end_page=page,
                end_offset=end,
                section=list(index.section_at(page, start)),
                source="tutor",
            )

    @staticmethod
    def _find_quote(index: Any, session: Session, quote: str) -> tuple[int, int, int] | None:
        needle = " ".join(quote.split())[:160]
        for page in range(session.start_page, min(session.end_page + 1, index.page_count)):
            text = index.page_text(page).clean()
            flat = " ".join(text.split())
            position = flat.find(needle)
            if position < 0:
                continue
            return page, position, position + len(needle)
        return None

    def cards_from_session(self, document_id: str, session: Session) -> list[dict[str, Any]]:
        """Turn the tutor's closing questions and dense passages into review cards."""
        plan = session.plan or {}
        existing = {card.front for card in self.study.cards(document_id)}
        created = []
        for question in plan.get("questions", []):
            front = str(question.get("text") or "").strip()
            back = str(question.get("answer") or "").strip()
            if not front or not back or front in existing:
                continue
            created.append(
                self.study.add_card(
                    document_id,
                    front=front,
                    back=back,
                    page=session.start_page,
                    source="tutor",
                ).to_dict()
            )
        for entry in plan.get("dense", []):
            front = str(entry.get("question") or "").strip()
            back = str(entry.get("explain") or "").strip()
            if not front or not back or front in existing:
                continue
            created.append(
                self.study.add_card(
                    document_id,
                    front=front,
                    back=back,
                    quote=str(entry.get("quote") or "").strip(),
                    page=session.start_page,
                    source="tutor",
                ).to_dict()
            )
        return created

    def check_answer(
        self, document_id: str, number: int, index: int, answer: str, version_id: str | None
    ) -> dict[str, Any]:
        """The tutor comments on the reader's answer to one closing question (and keeps it)."""
        session = self.sessions.get(document_id, number)
        plan = dict(session.plan or {})
        questions = list(plan.get("questions") or [])
        if not 0 <= index < len(questions):
            raise ConfigError(f"The session has no question {index + 1}")
        question = questions[index]
        text = answer.strip()
        comment = ""
        if text:
            document_index = self.registry.get(document_id, version_id)
            message = tutor_prompts.check_message(
                question=str(question.get("text") or ""),
                expected=str(question.get("answer") or ""),
                answer=text,
                passage=session_text(document_index, session, limit=6000),
            )
            client = self.chat_client()
            try:
                comment = tutor_prompts.check(
                    client, self.preferences.get().companion_language, message
                )
            finally:
                client.close()
        answers = dict(plan.get("answers") or {})
        answers[str(index)] = {"answer": text, "comment": comment}
        plan["answers"] = answers
        self.sessions.save_plan(document_id, number, plan)
        return {"index": index, "answer": text, "comment": comment}

    def concept_map(self, document_id: str, number: int, version_id: str | None) -> dict[str, Any]:
        """The concept map at the end of a session, and what is left of the book.

        The map is cumulative: the concepts this session brought (``new``), those met
        before that came back (``again``), the rest of the earlier ones (``earlier``) and
        the ones a later session already planned will bring (``ahead``). Each carries how
        often and where it occurs in the book.
        """
        sessions = self.sessions_of(document_id, version_id)
        session = self.sessions.get(document_id, number)
        index = self.registry.get(document_id, version_id)
        history = concept_history(sessions)
        new = [entry for entry in history if entry.session == number]
        again = [e for e in history if e.session < number and number in e.sessions]
        earlier = [e for e in history if e.session < number and number not in e.sessions]
        earlier = sorted(earlier, key=lambda entry: -entry.session)
        earlier = earlier[: max(0, _MAP_SIZE - len(new) - len(again))]
        ahead = sorted((e for e in history if e.session > number), key=lambda e: e.session)
        chosen = [
            *(("new", entry) for entry in new),
            *(("again", entry) for entry in again),
            *(("earlier", entry) for entry in earlier),
            *(("ahead", entry) for entry in ahead[:_MAP_AHEAD]),
        ]
        needles = {entry.needle for _, entry in chosen} | {entry.name for _, entry in chosen}
        found = index.occurrences(sorted(needles))
        concepts = []
        for state, entry in chosen:
            hits = found.get(entry.needle) or found.get(entry.name) or []
            pages = [page for page, _ in hits]
            concepts.append(
                {
                    "name": entry.name,
                    "term": entry.term,
                    "definition": entry.definition,
                    "session": entry.session,
                    "state": state,
                    "uses": sum(count for _, count in hits),
                    "first_page": pages[0] if pages else None,
                    "in_session": any(
                        session.start_page <= page <= session.end_page for page in pages
                    ),
                }
            )
        sections = [(entry.title, entry.page) for entry in index.info().toc if entry.level == 1]
        seconds = self.study.reading_time(document_id)
        return {
            "concepts": concepts,
            "pace": pace(sessions, number, sections, seconds, index.page_count),
        }

    # ------------------------------------------------------------------ dictionary
    def dictionary_entry(
        self, document_id: str, word: str, page: int, offset: int, version_id: str | None
    ) -> dict[str, Any]:
        document = self.library.get(document_id)
        index = self.registry.get(document_id, version_id)
        term = word.strip()
        hits = index.search(term, limit=200)
        uses = sum(len(boxes) for _, boxes in hits)
        pages = [number for number, _ in hits]
        key = (document_id, term.casefold())
        entry = self._dictionary.get(key)
        error: str | None = None
        if entry is None:
            prefs = self.preferences.get()
            context = build_context(index, Anchor(page, offset), None, size="short")
            message = dictionary_prompts.entry_message(
                word=term,
                title=document.title,
                authors=document.authors,
                language=None,
                sentence=context.selection or context.current,
                context=context.current,
                uses=uses,
            )
            try:
                client = self.chat_client()
            except ConfigError as exc:
                error = str(exc)
            else:
                try:
                    entry = dictionary_prompts.lookup(client, prefs.companion_language, message)
                    self._dictionary[key] = entry
                finally:
                    client.close()
        return {
            "word": term,
            "entry": entry,
            "error": error,
            "uses": uses,
            "pages": pages[:50],
            "page": page,
        }


def _hint(key: str | None) -> str | None:
    """The last characters of a key: enough to recognise it, useless to anyone else."""
    if not key or len(key) < 12:
        return None
    return f"••••{key[-4:]}"


def get_state(request: Request) -> AppState:
    return cast(AppState, request.app.state.polyglotpdf)


def nothing_translated(engine: str, report: dict[str, Any], lang: str | None = None) -> str:
    """What to tell the reader when every segment stayed in the original."""
    failures = " ".join(str(item) for item in report.get("failures") or []).lower()
    if "too many requests" in failures or "429" in failures:
        why = msg("nothing.throttled", lang, engine=engine)
    elif "could not be reached" in failures or "connection" in failures:
        why = msg("nothing.offline", lang, engine=engine)
    else:
        why = msg("nothing.silent", lang, engine=engine)
    return msg("nothing.translated", lang, why=why)
