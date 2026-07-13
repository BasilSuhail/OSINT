from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api as api
from app.api import app, get_session
from app.db_models import Base


def test_brain_ask_cors_preflight_allows_post():
    # A browser sends a CORS preflight (OPTIONS) before POST /brain/ask because
    # of the application/json content-type. GET-only allow_methods made every
    # preflight fail 400 → the ask box always showed "offline" (#419).
    client = TestClient(app)
    resp = client.options(
        "/brain/ask",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 200
    assert "POST" in resp.headers.get("access-control-allow-methods", "")


def _client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def test_ask_happy_path(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(api.client, "generate_json", lambda prompt: {"answer": "Border clashes."})
    body = client.post("/brain/ask", json={"question": "what is loudest?"}).json()
    assert body["answer"] == "Border clashes."
    assert body["context_digest"].startswith("sha256:")
    app.dependency_overrides.clear()


def test_ask_empty_question_is_422():
    client = _client()
    resp = client.post("/brain/ask", json={"question": ""})
    assert resp.status_code == 422
    app.dependency_overrides.clear()


def test_ask_ram_below_floor_returns_busy(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 100)
    monkeypatch.setattr(api.settings, "brain_min_free_mb", 1200)
    called = {"model": False}

    def _should_not_call(prompt):
        called["model"] = True
        return {"answer": "x"}

    monkeypatch.setattr(api.client, "generate_json", _should_not_call)
    body = client.post("/brain/ask", json={"question": "hi"}).json()
    assert "busy" in body["answer"].lower()
    assert body["context_digest"] is None
    assert called["model"] is False  # model never called when RAM is low
    app.dependency_overrides.clear()


def test_ask_ollama_down_returns_offline(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)

    def _boom(prompt):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(api.client, "generate_json", _boom)
    body = client.post("/brain/ask", json={"question": "hi"}).json()
    assert "offline" in body["answer"].lower()
    assert body["context_digest"] is None
    app.dependency_overrides.clear()


def test_ask_non_dict_model_output_degrades_gracefully(monkeypatch):
    # A small model can emit valid-but-non-object JSON (e.g. a bare list); it must
    # NOT 500 — the endpoint promises a typed answer at HTTP 200 for every failure.
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(api.client, "generate_json", lambda prompt: ["not", "a", "dict"])
    resp = client.post("/brain/ask", json={"question": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert "couldn't form" in body["answer"].lower()
    assert body["context_digest"] is None
    app.dependency_overrides.clear()


def test_ask_blank_answer_degrades_gracefully(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(api.client, "generate_json", lambda prompt: {"answer": "  "})
    body = client.post("/brain/ask", json={"question": "hi"}).json()
    assert "couldn't form" in body["answer"].lower()
    assert body["context_digest"] is None
    app.dependency_overrides.clear()


def test_ask_returns_sources_and_strips_bad_citations(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session: {
            "stories": [
                {
                    "n": 1,
                    "story_id": 5,
                    "title": "Border clashes",
                    "sources": ["Reuters"],
                    "corroboration": 0.8,
                    "contested": False,
                }
            ]
        },
    )
    monkeypatch.setattr(
        api.client, "generate_json", lambda prompt: {"answer": "Clashes [1]. See [9]."}
    )
    body = client.post("/brain/ask", json={"question": "what is happening?"}).json()
    assert len(body["sources"]) == 1 and body["sources"][0]["n"] == 1
    assert body["sources"][0]["outlets"] == ["Reuters"]
    assert "[9]" not in body["answer"]
    assert "[1]" in body["answer"]
    app.dependency_overrides.clear()


def test_ask_busy_has_empty_sources(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 100)
    monkeypatch.setattr(api.settings, "brain_min_free_mb", 1200)
    body = client.post("/brain/ask", json={"question": "hi"}).json()
    assert body["sources"] == []
    app.dependency_overrides.clear()
