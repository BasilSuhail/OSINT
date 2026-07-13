from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api as api
from app.api import app, get_session
from app.db_models import Base


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
