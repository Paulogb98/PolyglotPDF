"""The tutor's concept map across sessions, the reading pace, and pages the companion cites.

No AI is called: plans are written straight into the store, as the tutor would leave them.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient

from polyglotpdf.app.secrets import MemoryStore
from polyglotpdf.app.server import create_app
from polyglotpdf.app.sessions import Session, concept_history, known_before, pace
from polyglotpdf.companion.prompts import system_prompt
from polyglotpdf.companion.tutor import parse_plan, plan_message, upgrade_plan
from polyglotpdf.reading.context import Anchor, build_context
from polyglotpdf.reading.index import DocumentIndex

from .test_app import TOKEN, make_config, upload


def session(number: int, first: int, last: int, concepts: list[Any], status: str = "pending"):
    return Session(
        id=str(number),
        document_id="d",
        number=number,
        title=f"S{number}",
        start_page=first,
        end_page=last,
        status=status,
        plan={"concepts": concepts} if concepts else None,
        started_at=None,
        finished_at=None,
    )


def book(path: Path, pages: int = 36) -> Path:
    """A plain book: every page has a sentence; some pages name the concepts."""
    doc = pymupdf.open()
    for number in range(pages):
        page = doc.new_page(width=420, height=595)
        lines = [f"Page {number + 1} of the book goes on about the matter at hand."]
        if number in (2, 5):
            lines.append("Here Aufhebung appears, to negate and to keep.")
        if number == 14:
            lines.append("Mediation comes back, and Aufhe-")
            lines.append("bung too.")
        if number == 30:
            lines.append("Becoming is the truth of being and nothing.")
        for row, line in enumerate(lines):
            page.insert_text((40, 60 + 16 * row), line, fontsize=10)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_config(tmp_path), secrets=MemoryStore())) as test_client:
        test_client.headers["x-polyglotpdf-token"] = TOKEN
        yield test_client


# ---------------------------------------------------------------------- the plan
def test_concepts_carry_the_word_of_the_book_and_a_definition() -> None:
    plan = parse_plan(
        '{"concepts": [{"name": "suprassunção", "term": "Aufhebung",'
        ' "definition": "Negar e conservar no mesmo ato."}, "mediação", "Mediação"]}'
    )
    assert plan["concepts"] == [
        {
            "name": "suprassunção",
            "term": "Aufhebung",
            "definition": "Negar e conservar no mesmo ato.",
        },
        {"name": "mediação", "term": "", "definition": ""},
    ]
    # A plan stored by the first version (bare names) reads the same way.
    assert upgrade_plan({"concepts": ["ser"]}) == {
        "concepts": [{"name": "ser", "term": "", "definition": ""}]
    }


def test_the_plan_message_lists_what_earlier_sessions_brought() -> None:
    sessions = [
        session(1, 0, 11, [{"name": "suprassunção", "term": "Aufhebung"}]),
        session(2, 12, 23, ["mediação"]),
        session(3, 24, 35, ["devir"]),
    ]
    assert known_before(sessions, 3) == ["suprassunção (Aufhebung)", "mediação"]
    message = plan_message(
        title="Livro",
        authors=None,
        session_title="S3",
        number=3,
        total=3,
        first_label="25",
        last_label="36",
        text="…",
        known=known_before(sessions, 3),
    )
    assert "Concepts met in earlier sessions: suprassunção (Aufhebung); mediação" in message.content


def test_the_history_keeps_where_each_concept_first_appeared() -> None:
    history = concept_history(
        [
            session(2, 12, 23, [{"name": "suspensão", "term": "Aufhebung"}, "mediação"]),
            session(1, 0, 11, [{"name": "suprassunção", "term": "Aufhebung", "definition": "d"}]),
        ]
    )
    # Renamed in session 2, the same word of the book is still the same concept.
    assert [(entry.name, entry.session, entry.sessions) for entry in history] == [
        ("suprassunção", 1, [1, 2]),
        ("mediação", 2, [2]),
    ]
    assert history[0].definition == "d" and history[0].needle == "Aufhebung"


# ---------------------------------------------------------------------- the pace
def test_the_pace_counts_what_is_left_of_the_part_and_how_long_it_takes() -> None:
    sessions = [
        session(1, 0, 9, [], "done"),
        session(2, 10, 19, [], "done"),
        session(3, 20, 29, []),
        session(4, 30, 39, []),
        session(5, 40, 49, []),
    ]
    parts = [("Primeira parte", 0), ("Segunda parte", 40)]
    # 20 pages done in 40 minutes: 2 minutes a page.
    assert pace(sessions, 2, parts, 2400, 50) == {
        "scope": "section",
        "title": "Primeira parte",
        "sessions_left": 2,
        "minutes_left": 40,
    }
    assert pace(sessions, 4, parts, 2400, 50)["scope"] == "book"  # the part ends there
    assert pace(sessions, 2, [], 30, 50) == {
        "scope": "book",
        "title": None,
        "sessions_left": 3,
        "minutes_left": None,  # under a minute read: no pace yet
    }
    assert pace(sessions, 5, parts, 2400, 50)["scope"] == "done"


# ---------------------------------------------------------------------- the map
def test_the_map_is_cumulative_and_shows_what_is_ahead(client: TestClient, tmp_path: Path) -> None:
    document = upload(client, book(tmp_path / "book.pdf"))["document"]
    base = f"/api/documents/{document['id']}"
    sessions = client.get(f"{base}/sessions").json()["sessions"]
    assert len(sessions) == 3
    state = client.app.state.polyglotpdf  # type: ignore[attr-defined]
    plans = {
        1: [{"name": "suprassunção", "term": "Aufhebung", "definition": "Negar e conservar."}],
        2: [
            {"name": "mediação", "term": "Mediation", "definition": "O oposto do imediato."},
            {"name": "suprassunção", "term": "Aufhebung", "definition": ""},
        ],
        3: [{"name": "devir", "term": "Becoming", "definition": "Verdade de ser e nada."}],
    }
    for number, concepts in plans.items():
        state.sessions.save_plan(document["id"], number, {"concepts": concepts})
    client.post(f"{base}/sessions/1/finish")

    answer = client.get(f"{base}/sessions/2/concepts").json()
    concepts = {concept["name"]: concept for concept in answer["concepts"]}
    assert [concept["name"] for concept in answer["concepts"]] == [
        "mediação",
        "suprassunção",
        "devir",
    ]
    assert concepts["mediação"]["state"] == "new"
    back = concepts["suprassunção"]
    assert back["state"] == "again" and back["session"] == 1
    assert back["definition"] == "Negar e conservar."  # the first definition stays
    # Found by the book's own word, hyphenated across lines on p. 15 included.
    assert back["uses"] == 3 and back["first_page"] == 2 and back["in_session"]
    assert concepts["devir"]["state"] == "ahead" and concepts["devir"]["session"] == 3
    assert answer["pace"]["scope"] == "book" and answer["pace"]["sessions_left"] == 1


# ---------------------------------------------------------------------- page references
def test_the_context_marks_pages_so_the_companion_can_cite_them(tmp_path: Path) -> None:
    index = DocumentIndex.open(book(tmp_path / "book.pdf", pages=6))
    try:
        text = index.page_text(3).clean()
        context = build_context(index, Anchor(3, 0), Anchor(3, len(text)))
    finally:
        index.close()
    assert context.before.startswith("[p. 1]")
    assert "[p. 3]" in context.before and "[p. 5]" in context.after
    assert "(p. N)" in system_prompt("pt-BR")
