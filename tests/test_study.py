"""Highlights, notes, bookmarks, the notebook, review cards and the tutor's sessions.

The AI parts (the session plan and the dictionary entry) run against the "echo" engine,
so the tests check the plumbing — anchoring, scheduling, the session ranges — and not
the quality of an answer.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from polyglotpdf.app.db import MIGRATIONS, Database
from polyglotpdf.app.preferences import Preferences
from polyglotpdf.app.secrets import MemoryStore
from polyglotpdf.app.server import create_app
from polyglotpdf.app.sessions import MAX_PAGES, build_ranges
from polyglotpdf.app.study import GRADES
from polyglotpdf.companion.dictionary import parse_entry
from polyglotpdf.companion.tutor import parse_plan
from polyglotpdf.reading.index import DocumentIndex

from .test_app import TOKEN, make_config, upload


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_config(tmp_path), secrets=MemoryStore())) as test_client:
        test_client.headers["x-polyglotpdf-token"] = TOKEN
        yield test_client


@pytest.fixture
def document(client: TestClient, sample_pdf: Path) -> dict[str, Any]:
    result: dict[str, Any] = upload(client, sample_pdf)["document"]
    return result


def make_mark(client: TestClient, document_id: str, **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "highlight",
        "color": "yellow",
        "quote": "the parameter controls the growth",
        "start": {"page": 0, "offset": 60},
        "end": {"page": 0, "offset": 90},
    }
    body.update(changes)
    response = client.post(f"/api/documents/{document_id}/marks", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


# ---------------------------------------------------------------------- marks
def test_highlight_becomes_a_note_when_the_reader_writes_on_it(
    client: TestClient, document: dict[str, Any]
) -> None:
    mark = make_mark(client, document["id"])
    assert mark["kind"] == "highlight"
    assert mark["section"] == ["1. Introduction"], "filed under the section it was made in"

    updated = client.patch(
        f"/api/marks/{mark['id']}", json={"note": "comparar com o capítulo 2", "tags": ["dúvida"]}
    ).json()
    assert updated["kind"] == "note"
    assert updated["note"] == "comparar com o capítulo 2"
    assert updated["tags"] == ["dúvida"]

    only_notes = client.get(f"/api/documents/{document['id']}/marks", params={"kind": "note"})
    assert [item["id"] for item in only_notes.json()["marks"]] == [mark["id"]]

    on_page = client.get(f"/api/documents/{document['id']}/marks", params={"page": 0})
    assert len(on_page.json()["marks"]) == 1
    assert client.get(f"/api/documents/{document['id']}/marks", params={"page": 5}).json() == {
        "marks": []
    }

    assert client.delete(f"/api/marks/{mark['id']}").status_code == 204
    assert client.get(f"/api/documents/{document['id']}/marks").json() == {"marks": []}


def test_a_highlight_can_stay_off_the_notebook_until_it_is_annotated(
    client: TestClient, document: dict[str, Any]
) -> None:
    mark = make_mark(client, document["id"], in_notebook=False)
    assert mark["in_notebook"] is False
    # It is still painted on the page...
    assert len(client.get(f"/api/documents/{document['id']}/marks").json()["marks"]) == 1
    # ...but the notebook does not hold it.
    assert client.get(f"/api/documents/{document['id']}/notebook").json()["counts"]["total"] == 0

    filed = client.patch(f"/api/marks/{mark['id']}", json={"note": "voltar aqui"}).json()
    assert filed["in_notebook"] is True, "writing a note files the mark"
    assert client.get(f"/api/documents/{document['id']}/notebook").json()["counts"]["total"] == 1


def test_an_unknown_colour_is_refused(client: TestClient, document: dict[str, Any]) -> None:
    response = client.post(
        f"/api/documents/{document['id']}/marks",
        json={
            "color": "roxo",
            "quote": "x",
            "start": {"page": 0, "offset": 0},
            "end": {"page": 0, "offset": 1},
        },
    )
    assert response.status_code == 400
    assert "roxo" in response.json()["detail"]


def test_bookmarks_toggle(client: TestClient, document: dict[str, Any]) -> None:
    marked = client.post(f"/api/documents/{document['id']}/bookmarks", json={"page": 0}).json()
    assert marked["marked"] is True
    assert marked["bookmarks"] == [
        {"page": 0, "label": "", "created_at": marked["bookmarks"][0]["created_at"]}
    ]
    again = client.post(f"/api/documents/{document['id']}/bookmarks", json={"page": 0}).json()
    assert again["marked"] is False and again["bookmarks"] == []


# ---------------------------------------------------------------------- notebook
def test_the_notebook_groups_marks_by_chapter_and_counts_the_concepts(
    client: TestClient, document: dict[str, Any]
) -> None:
    make_mark(client, document["id"], tags=["crescimento"])
    make_mark(
        client,
        document["id"],
        quote="the rate at which the population changes",
        note="ver a equação (1)",
        tags=["crescimento", "taxa"],
        start={"page": 0, "offset": 120},
        end={"page": 0, "offset": 160},
    )
    notebook = client.get(f"/api/documents/{document['id']}/notebook").json()
    assert notebook["counts"]["total"] == 2
    assert notebook["counts"]["highlights"] == 1
    assert notebook["counts"]["notes"] == 1
    assert len(notebook["chapters"]) == 1
    assert len(notebook["chapters"][0]["marks"]) == 2
    assert notebook["concepts"][0] == {"name": "crescimento", "count": 2}

    client.post(f"/api/documents/{document['id']}/reading-time", json={"seconds": 90})
    total = client.post(f"/api/documents/{document['id']}/reading-time", json={"seconds": 30})
    assert total.json() == {"seconds": 120}
    assert client.get(f"/api/documents/{document['id']}/notebook").json()["reading_seconds"] == 120


# ---------------------------------------------------------------------- cards
def test_review_schedules_the_card_further_out_on_every_good_answer(
    client: TestClient, document: dict[str, Any]
) -> None:
    card = client.post(
        f"/api/documents/{document['id']}/cards",
        json={"front": "O que é o parâmetro?", "back": "Controla o crescimento.", "page": 0},
    ).json()
    assert card["state"] == "new"

    queue = client.get(f"/api/documents/{document['id']}/review").json()
    assert queue["counts"] == {"total": 1, "new": 1, "hard": 0, "ok": 0}
    grades = [option["grade"] for option in queue["cards"][0]["schedule"]]
    assert grades == list(GRADES)
    labels = {o["grade"]: o["label"] for o in queue["cards"][0]["schedule"]}
    assert labels["again"] == "em 10 min" and labels["hard"] == "amanhã"

    good = client.post(f"/api/cards/{card['id']}/review", json={"grade": "good"}).json()
    assert good["reps"] == 1 and good["interval_days"] == 4.0
    assert client.get(f"/api/documents/{document['id']}/review").json()["counts"]["total"] == 0

    again = client.post(f"/api/cards/{card['id']}/review", json={"grade": "again"}).json()
    assert again["lapses"] == 1 and again["interval_days"] == 0.0
    assert again["ease"] < good["ease"]
    # "De novo" puts the card ten minutes away, so it leaves today's queue too.
    assert client.get(f"/api/documents/{document['id']}/review").json()["counts"]["total"] == 0

    assert client.post(f"/api/cards/{card['id']}/review", json={"grade": "meh"}).status_code == 400
    assert client.delete(f"/api/cards/{card['id']}").status_code == 204


# ---------------------------------------------------------------------- tutor sessions
def test_sessions_cover_the_whole_document_without_gaps(
    client: TestClient, document: dict[str, Any]
) -> None:
    listing = client.get(f"/api/documents/{document['id']}/sessions").json()
    sessions = listing["sessions"]
    assert sessions and sessions[0]["start_page"] == 0
    assert sessions[-1]["end_page"] == document["pages"] - 1
    for before, after in pairwise(sessions):
        assert after["start_page"] == before["end_page"] + 1
    assert listing["current"] == 1

    started = client.post(f"/api/documents/{document['id']}/sessions/1/start").json()
    assert started["status"] == "running"
    finished = client.post(f"/api/documents/{document['id']}/sessions/1/finish").json()
    assert finished["status"] == "done" and finished["finished_at"]
    assert client.get(f"/api/documents/{document['id']}/settings").json()["session_number"] == 2


def test_session_ranges_split_long_chapters(paper_pdf: Path) -> None:
    index = DocumentIndex.open(paper_pdf)
    try:
        ranges = build_ranges(index)
    finally:
        index.close()
    assert ranges[0][1] == 0
    assert ranges[-1][2] == index.page_count - 1
    assert all(last - first + 1 <= MAX_PAGES for _, first, last in ranges)


def test_document_settings_remember_how_the_book_opens(
    client: TestClient, document: dict[str, Any]
) -> None:
    saved = client.put(
        f"/api/documents/{document['id']}/settings", json={"open_mode": "tutor", "layout": "side"}
    ).json()
    assert saved["open_mode"] == "tutor" and saved["layout"] == "side"
    assert client.get(f"/api/documents/{document['id']}/settings").json()["open_mode"] == "tutor"


# ---------------------------------------------------------------------- AI answers
def test_the_tutor_plan_is_read_from_json_even_inside_a_code_fence() -> None:
    plan = parse_plan(
        "```json\n"
        + json.dumps(
            {
                "intro": "Este trecho discute o começo.",
                "expect": ["a", "b", "c", "d"],
                "concepts": ["ser", "nada"],
                "dense": [{"quote": "o começo é um resultado", "why": "difícil", "explain": "…"}],
                "questions": [
                    {"text": "Por quê?", "answer": "Porque…"},
                    {"text": "E daí?", "answer": "Porque…"},
                    {"text": "Como?", "answer": "Assim…"},
                    {"text": "demais", "answer": "…"},
                ],
            }
        )
        + "\n```"
    )
    assert plan["intro"].startswith("Este trecho")
    assert len(plan["expect"]) == 3
    assert len(plan["questions"]) == 3
    assert plan["dense"][0]["quote"] == "o começo é um resultado"


def test_a_dictionary_entry_keeps_the_common_sense_and_the_one_in_the_book() -> None:
    entry = parse_entry(
        json.dumps(
            {
                "word": "Unmittelbares",
                "pronunciation": "[ˈʊnmɪtəlbaːʁəs]",
                "grammar": "substantivado, neutro",
                "senses": [
                    {"gloss": "o que é direto", "common": True},
                    {"gloss": "o imediato", "common": False},
                ],
                "in_book": "Termo técnico.",
                "related": ["Mittelbares", "Vermittlung", "Sein", "demais"],
            }
        )
    )
    assert entry["word"] == "Unmittelbares"
    assert [sense["common"] for sense in entry["senses"]] == [True, False]
    assert len(entry["related"]) == 3


def test_the_dictionary_counts_the_uses_in_the_document(
    client: TestClient, document: dict[str, Any]
) -> None:
    response = client.get(
        f"/api/documents/{document['id']}/dictionary", params={"word": "parameter", "page": 0}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["word"] == "parameter"
    assert body["uses"] >= 1 and body["pages"] == [0]
    # Without an AI engine the panel still opens: the entry is missing, not an error page.
    assert body["entry"] is None and "chave" in (body["error"] or "")


# ---------------------------------------------------------------------- redesign additions
def test_the_layout_names_the_language_of_the_book(
    client: TestClient, document: dict[str, Any]
) -> None:
    assert client.get(f"/api/documents/{document['id']}/layout").json()["language"] == "en"


def test_language_detection_by_function_words_and_by_script() -> None:
    from polyglotpdf.reading.language import detect_language

    german = (
        "Der Anfang ist nicht das reine Nichts, sondern ein Nichts, von dem etwas ausgehen "
        "soll; das Sein ist also schon im Anfang enthalten. Der Anfang enthält also beides, "
        "Sein und Nichts; er ist die Einheit von Sein und Nichts."
    ) * 2
    assert detect_language(german) == "de"
    assert detect_language("Начало не есть чистое ничто, но такое ничто, " * 6) == "ru"
    assert detect_language("tão curto") is None


def test_a_closing_answer_is_kept_with_the_tutor_comment(
    client: TestClient, document: dict[str, Any]
) -> None:
    listing = client.get(f"/api/documents/{document['id']}/sessions").json()
    number = listing["sessions"][0]["number"]
    app_state = client.app.state.polyglotpdf  # type: ignore[attr-defined]
    app_state.sessions.save_plan(
        document["id"],
        number,
        {
            "concepts": ["parameter"],
            "questions": [{"text": "O que faz o parâmetro?", "answer": "x"}],
        },
    )
    # An empty answer needs no AI: it is kept, and the comment is empty.
    answered = client.post(
        f"/api/documents/{document['id']}/sessions/{number}/answer",
        json={"index": 0, "answer": "  "},
    ).json()
    assert answered == {"index": 0, "answer": "", "comment": ""}
    missing = client.post(
        f"/api/documents/{document['id']}/sessions/{number}/answer",
        json={"index": 3, "answer": "algo"},
    )
    assert missing.status_code == 400

    concepts = client.get(f"/api/documents/{document['id']}/sessions/{number}/concepts").json()
    assert concepts["concepts"][0]["name"] == "parameter"
    assert concepts["concepts"][0]["uses"] >= 1 and concepts["concepts"][0]["first_page"] == 0


def test_a_stored_key_is_shown_only_by_its_last_characters(client: TestClient) -> None:
    client.put("/api/engines/anthropic/key", json={"api_key": "sk-ant-api03-abcdefgh4f2a"})
    engine = next(
        e for e in client.get("/api/engines").json()["engines"] if e["name"] == "anthropic"
    )
    assert engine["key_hint"] == "••••4f2a"
    assert "abcdefgh" not in str(engine)


# ---------------------------------------------------------------------- migrations
def test_portuguese_values_saved_before_the_rename_are_migrated(tmp_path: Path) -> None:
    """A library written while the stored values were still Portuguese keeps working."""
    path = tmp_path / "library.sqlite3"
    database = Database(path)
    database.execute(
        "INSERT INTO documents (id, title, filename, format, pages, size, sha256, added_at)"
        " VALUES ('d1', 'Book', 'book.pdf', 'pdf', 1, 1, 'sha256', '2026-01-01T00:00:00+00:00')"
    )
    database.execute(
        "INSERT INTO marks (id, document_id, kind, color, quote, start_page, start_offset,"
        " end_page, end_offset, created_at, updated_at) VALUES ('m1', 'd1', 'highlight',"
        " 'amarelo', 'a passage', 0, 0, 0, 9, '2026-01-01', '2026-01-01')"
    )
    database.execute("INSERT INTO doc_settings (document_id, layout) VALUES ('d1', 'lado')")
    # Rewind the schema so opening it again runs the renaming migration.
    database.execute(f"PRAGMA user_version = {len(MIGRATIONS) - 1}")
    database.close()

    database = Database(path)
    assert database.one("SELECT color FROM marks WHERE id = 'm1'")["color"] == "yellow"
    assert database.one("SELECT layout FROM doc_settings")["layout"] == "side"
    database.close()


def test_a_preferences_file_with_the_old_colour_still_loads() -> None:
    prefs = Preferences.from_dict({"reading": {"highlight_color": "amarelo"}})
    assert prefs.reading.highlight_color == "yellow"
    assert Preferences.from_dict({"reading": {"highlight_color": "coral"}}).reading.highlight_color
