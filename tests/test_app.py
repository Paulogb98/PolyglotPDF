"""Reader application API: access control, library, reader, keys, companion and jobs.

Everything runs offline: the companion uses the "echo" engine and translations the
"pseudo" engine. Jobs run in a worker thread, except one test that exercises the
child process used in production.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from polyglotpdf.app.config import AppConfig
from polyglotpdf.app.jobs import JobManager, JobStatus
from polyglotpdf.app.secrets import MemoryStore
from polyglotpdf.app.server import create_app
from polyglotpdf.config import Settings
from polyglotpdf.translation.engines import list_engines

TOKEN = "test-token"


def make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        data_dir=tmp_path / "data",
        token=TOKEN,
        allowed_hosts=frozenset({"testserver"}),
        static_dir=tmp_path / "static",  # interface not built
        job_isolation="thread",
        echo_delay=0,
    )


@pytest.fixture(autouse=True)
def no_environment_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for engine in list_engines():
        for variable in engine.key_env:
            monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_config(tmp_path), secrets=MemoryStore())) as test_client:
        test_client.headers["x-polyglotpdf-token"] = TOKEN
        yield test_client


def upload(client: TestClient, path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        response = client.post(
            "/api/documents", files={"file": (path.name, file, "application/pdf")}
        )
    assert response.status_code in (200, 201), response.text
    result: dict[str, Any] = response.json()
    return result


def page_text(client: TestClient, document_id: str, **params: str) -> str:
    layer = client.get(f"/api/documents/{document_id}/pages/0/text", params=params).json()
    return "".join(word[5] for word in layer["words"])


def events(response: Any) -> list[tuple[str, Any]]:
    assert response.status_code == 200, response.text
    parsed = []
    for block in response.text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        parsed.append((fields["event"], json.loads(fields["data"])))
    return parsed


def wait_for(client: TestClient, job_id: str, timeout: float = 120) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job: dict[str, Any] = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish")


# ---------------------------------------------------------------------- access control
def test_access_needs_the_token_and_a_local_host(tmp_path: Path) -> None:
    with TestClient(create_app(make_config(tmp_path), secrets=MemoryStore())) as anonymous:
        assert anonymous.get("/api/documents").status_code == 401
        assert anonymous.get("/").status_code == 401
        assert anonymous.get("/?token=wrong").status_code == 403
        entry = anonymous.get(f"/?token={TOKEN}", follow_redirects=False)
        assert entry.status_code == 303
        cookie = entry.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        allowed = anonymous.get("/api/documents")
        assert allowed.status_code == 200
        assert "default-src 'self'" in allowed.headers["content-security-policy"]
        assert allowed.headers["x-frame-options"] == "DENY"
        assert anonymous.get("/api/documents", headers={"host": "evil.example"}).status_code == 400
        home = anonymous.get("/")
        assert home.status_code == 200 and "npm --prefix frontend" in home.text


# ---------------------------------------------------------------------- library and reader
def test_library_import_list_update_and_remove(client: TestClient, sample_pdf: Path) -> None:
    created = upload(client, sample_pdf)
    document = created["document"]
    assert created["created"] and document["title"] == "A Study of Things"
    assert document["pages"] == 1 and document["format"] == "pdf"
    again = upload(client, sample_pdf)
    assert not again["created"] and again["document"]["id"] == document["id"]

    doc_id = document["id"]
    found = client.get("/api/documents", params={"q": "study"}).json()["documents"]
    assert [d["id"] for d in found] == [doc_id]
    assert client.get("/api/documents", params={"q": "zzz"}).json()["documents"] == []
    changes = {"title": "Outro título", "last_page": 0, "favorite": True, "opened": True}
    updated = client.patch(f"/api/documents/{doc_id}", json=changes).json()
    assert updated["title"] == "Outro título" and updated["favorite"] and updated["progress"] == 1
    assert client.patch(f"/api/documents/{doc_id}", json={"colour": "red"}).status_code == 422
    assert client.get(f"/api/documents/{doc_id}/cover").content.startswith(b"\x89PNG")
    assert client.get(f"/api/documents/{doc_id}/file").content.startswith(b"%PDF")
    text_file = client.post("/api/documents", files={"file": ("notes.txt", b"hi", "text/plain")})
    assert text_file.status_code == 400

    assert client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert client.get(f"/api/documents/{doc_id}").status_code == 404


def test_reader_endpoints(client: TestClient, sample_pdf: Path) -> None:
    doc_id = upload(client, sample_pdf)["document"]["id"]
    layout = client.get(f"/api/documents/{doc_id}/layout").json()
    assert layout["page_count"] == 1 and layout["pages"] == [[595, 842]]
    assert layout["title"] == "A Study of Things" and layout["toc"] == []
    image = client.get(f"/api/documents/{doc_id}/pages/0/image", params={"scale": 0.5})
    assert image.headers["content-type"] == "image/png"
    assert "immutable" in image.headers["cache-control"]
    layer = client.get(f"/api/documents/{doc_id}/pages/0/text").json()
    assert layer["label"] == "1" and layer["words"][0][4:] == [0, "A "]
    assert client.get(f"/api/documents/{doc_id}/pages/5/text").status_code == 404
    assert (
        client.get(f"/api/documents/{doc_id}/pages/0/image", params={"scale": 9}).status_code == 422
    )
    hits = client.get(f"/api/documents/{doc_id}/search", params={"q": "growth"}).json()
    assert hits["total"] >= 1 and hits["hits"][0]["page"] == 0

    start = page_text(client, doc_id).index("controls")
    body = {"start": {"page": 0, "offset": start}, "end": {"page": 0, "offset": start + 8}}
    context = client.post(f"/api/documents/{doc_id}/context", json=body).json()
    assert context["selection"] == "controls" and context["section"] == ["1. Introduction"]
    assert "Growth is fast" in context["after"]


# ---------------------------------------------------------------------- keys and preferences
def test_keys_are_stored_but_never_returned(client: TestClient) -> None:
    engines = {e["name"]: e for e in client.get("/api/engines").json()["engines"]}
    assert engines["google"]["ready"] and not engines["deepseek"]["ready"]
    assert client.get("/api/engines").json()["companion_engine"] is None

    stored = client.put("/api/engines/deepseek/key", json={"api_key": "sk-secret-123"}).json()
    assert stored["key_source"] == "app" and stored["ready"]
    exposed = "".join(
        client.get(url).text for url in ("/api/engines", "/api/preferences", "/api/info")
    )
    assert "sk-secret-123" not in exposed
    assert client.get("/api/engines").json()["companion_engine"] == "deepseek"
    assert client.delete("/api/engines/deepseek/key").json()["key_source"] is None
    assert client.put("/api/engines/babelfish/key", json={"api_key": "x"}).status_code == 400


def test_preferences_are_validated(client: TestClient) -> None:
    changes = {"target_lang": "es", "engines": {"ollama": {"model": "llama3"}}}
    prefs = client.put("/api/preferences", json=changes).json()
    assert prefs["target_lang"] == "es" and prefs["engines"]["ollama"]["model"] == "llama3"
    assert client.put("/api/preferences", json={"companion_engine": "google"}).status_code == 400
    assert client.put("/api/preferences", json={"unknown": 1}).status_code == 400
    engines = {e["name"]: e for e in client.get("/api/engines").json()["engines"]}
    assert engines["ollama"]["model"] == "llama3"
    actions = client.get("/api/companion/actions").json()["actions"]
    assert {"key": "explain", "label": "Explicar"} in actions


# ---------------------------------------------------------------------- companion
def test_companion_conversation(client: TestClient, sample_pdf: Path) -> None:
    doc_id = upload(client, sample_pdf)["document"]["id"]
    start = page_text(client, doc_id).index("Growth is fast")
    ask = {
        "document_id": doc_id,
        "start": {"page": 0, "offset": start},
        "end": {"page": 0, "offset": start + len("Growth is fast")},
        "action": "explain",
    }
    # What the reader is told comes in the interface's language (Portuguese by default).
    no_engine = client.post("/api/companion/ask", json=ask)
    assert no_engine.status_code == 400 and "chave" in no_engine.json()["detail"]
    in_english = client.post(
        "/api/companion/ask", json=ask, headers={"X-PolyglotPDF-Language": "en"}
    )
    assert "API key" in in_english.json()["detail"]

    client.put("/api/preferences", json={"companion_engine": "echo"})
    first = events(client.post("/api/companion/ask", json=ask))
    kinds = [kind for kind, _ in first]
    assert kinds[0] == "thread" and kinds[-1] == "done" and "delta" in kinds
    thread = first[0][1]
    assert thread["quote"] == "Growth is fast"
    assert thread["context"]["section"] == ["1. Introduction"]
    answer = "".join(data["text"] for kind, data in first if kind == "delta")
    assert "<selected_passage>\nGrowth is fast\n</selected_passage>" in answer

    follow = {
        "document_id": doc_id,
        "thread_id": thread["id"],
        "action": "ask",
        "question": "E depois?",
    }
    later = "".join(
        d["text"] for k, d in events(client.post("/api/companion/ask", json=follow)) if k == "delta"
    )
    assert "E depois?" in later and "<document>" not in later

    stored = client.get(f"/api/threads/{thread['id']}").json()
    assert [m["role"] for m in stored["messages"]] == ["user", "assistant", "user", "assistant"]
    assert stored["messages"][0]["text"] == "Explicar"
    assert stored["messages"][2]["text"] == "E depois?"
    listing = client.get(f"/api/documents/{doc_id}/threads").json()["threads"]
    assert len(listing) == 1 and listing[0]["message_count"] == 4
    assert "Growth is fast" in client.get(f"/api/threads/{thread['id']}/context").json()["current"]
    assert client.post("/api/companion/ask", json={**ask, "action": "ask"}).status_code == 400
    assert client.delete(f"/api/threads/{thread['id']}").status_code == 204


def test_companion_about_a_whole_page(client: TestClient, sample_pdf: Path) -> None:
    doc_id = upload(client, sample_pdf)["document"]["id"]
    client.put("/api/preferences", json={"companion_engine": "echo"})
    ask = {"document_id": doc_id, "start": {"page": 0, "offset": 0}, "action": "summarize"}
    thread = events(client.post("/api/companion/ask", json=ask))[0][1]
    assert thread["whole_page"] and thread["quote"] == "Página 1"


# ---------------------------------------------------------------------- jobs
def test_estimate_and_translation_jobs(client: TestClient, sample_pdf: Path) -> None:
    doc_id = upload(client, sample_pdf)["document"]["id"]
    estimate = wait_for(
        client, client.post(f"/api/documents/{doc_id}/estimate", json={}).json()["id"]
    )
    assert estimate["status"] == "done" and estimate["result"]["segments"] >= 6

    assert (
        client.post(f"/api/documents/{doc_id}/translate", json={"engine": "deepseek"}).status_code
        == 400
    )
    bad_pages = {"engine": "pseudo", "pages": "9"}
    assert client.post(f"/api/documents/{doc_id}/translate", json=bad_pages).status_code == 400

    started = client.post(f"/api/documents/{doc_id}/translate", json={"engine": "pseudo"})
    assert started.status_code == 202 and started.json()["params"]["target_lang"] == "pt-BR"
    done = wait_for(client, started.json()["id"])
    assert done["status"] == "done" and done["progress"] == 1 and done["version_id"]
    version = done["version_id"]
    versions = client.get(f"/api/documents/{doc_id}").json()["versions"]
    assert [v["id"] for v in versions] == [version] and versions[0]["failed"] == 0
    translated = page_text(client, doc_id, version=version)
    assert any(ch in translated for ch in "àéîöû")
    download = client.get(f"/api/documents/{doc_id}/file", params={"version": version})
    assert download.content.startswith(b"%PDF")
    assert client.delete(f"/api/documents/{doc_id}/versions/{version}").status_code == 204
    assert client.get(f"/api/documents/{doc_id}").json()["versions"] == []


def test_a_translation_with_nothing_translated_fails_clearly(
    client: TestClient, sample_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from polyglotpdf.app import state as state_module
    from polyglotpdf.translation import google

    def refuse(url: str, **_: Any) -> str:
        raise google.Refused("Google Translate refused the request (too many requests)")

    def quick_settings() -> Settings:
        settings = Settings()
        settings.translation.max_retries = 1  # no waiting between attempts
        return settings

    monkeypatch.setattr(google, "_request", refuse)
    monkeypatch.setattr(state_module, "Settings", quick_settings)
    doc_id = upload(client, sample_pdf)["document"]["id"]
    job = client.post(f"/api/documents/{doc_id}/translate", json={"engine": "google"}).json()
    finished = wait_for(client, job["id"])
    assert finished["status"] == "failed"
    assert finished["error"].startswith("Nada foi traduzido")
    assert "excesso de uso" in finished["error"]
    assert client.get(f"/api/documents/{doc_id}").json()["versions"] == []


def test_translation_can_be_cancelled(client: TestClient, paper_pdf: Path) -> None:
    doc_id = upload(client, paper_pdf)["document"]["id"]
    job = client.post(f"/api/documents/{doc_id}/translate", json={"engine": "pseudo"}).json()
    client.post(f"/api/jobs/{job['id']}/cancel")
    finished = wait_for(client, job["id"])
    assert finished["status"] == "cancelled"
    assert client.get(f"/api/documents/{doc_id}").json()["versions"] == []


def test_jobs_run_in_a_child_process(sample_pdf: Path) -> None:
    manager = JobManager(isolation="process")
    try:
        payload = {"settings": Settings().to_dict(), "input": str(sample_pdf)}
        job = manager.submit("estimate", "document", {}, payload)
        deadline = time.monotonic() + 120
        while not job.finished and time.monotonic() < deadline:
            time.sleep(0.1)
        assert job.status is JobStatus.DONE, job.error
        assert job.result is not None and job.result["segments"] >= 6
        assert job.stages["analyze"] == (1, 1)
    finally:
        manager.shutdown()
