"""Request bodies of the API (responses are plain JSON built by the domain objects)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnchorIn(_Body):
    page: int = Field(ge=0)
    offset: int = Field(ge=0)


class DocumentPatch(_Body):
    title: str | None = Field(default=None, max_length=500)
    authors: str | None = Field(default=None, max_length=1000)
    last_page: int | None = Field(default=None, ge=0)
    favorite: bool | None = None
    opened: bool = False


class TranslateRequest(_Body):
    engine: str
    model: str | None = Field(default=None, max_length=200)
    source_lang: str = "auto"
    target_lang: str = "pt-BR"
    pages: str | None = Field(default=None, max_length=200)  # "1-3,7"; None = all
    translate_code: bool = False


class EstimateRequest(_Body):
    pages: str | None = Field(default=None, max_length=200)


class KeyIn(_Body):
    api_key: str = Field(min_length=1, max_length=4096)


class CheckIn(_Body):
    api_key: str | None = Field(default=None, max_length=4096)
    base_url: str | None = Field(default=None, max_length=500)


class ContextRequest(_Body):
    version_id: str | None = None
    start: AnchorIn
    end: AnchorIn | None = None  # None: the whole page of ``start``


class AskRequest(_Body):
    document_id: str
    version_id: str | None = None
    thread_id: str | None = None  # continue a conversation
    start: AnchorIn | None = None  # new conversation: the passage (or page) it is about
    end: AnchorIn | None = None
    action: str = "ask"
    question: str | None = Field(default=None, max_length=4000)


class MarkIn(_Body):
    version_id: str | None = None
    kind: str = "highlight"
    color: str = "yellow"
    quote: str = Field(max_length=8000)
    note: str | None = Field(default=None, max_length=8000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    start: AnchorIn
    end: AnchorIn
    section: list[str] = Field(default_factory=list, max_length=8)
    source: str = "reader"
    in_notebook: bool = True


class MarkPatch(_Body):
    color: str | None = None
    note: str | None = Field(default=None, max_length=8000)
    tags: list[str] | None = Field(default=None, max_length=12)
    kind: str | None = None
    in_notebook: bool | None = None


class BookmarkIn(_Body):
    page: int = Field(ge=0)
    label: str = Field(default="", max_length=200)


class CardIn(_Body):
    front: str = Field(max_length=2000)
    back: str = Field(max_length=8000)
    quote: str = Field(default="", max_length=8000)
    page: int = Field(default=0, ge=0)
    mark_id: str | None = None
    source: str = "reader"


class ReviewIn(_Body):
    grade: str


class ReadingTimeIn(_Body):
    seconds: int = Field(ge=0, le=3600)


class DocSettingsIn(_Body):
    open_mode: str | None = None
    layout: str | None = None
    version_id: str | None = None
    session_number: int | None = Field(default=None, ge=1)


class AnswerIn(_Body):
    index: int = Field(ge=0, le=20)
    answer: str = Field(max_length=4000)
