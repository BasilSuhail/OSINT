"""(source)/(thinking) chip fuel in the ask payload (#476).

The frontend renders [n] as clickable source chips and marks unsupported
sentences (the brain's own analysis) with thinking chips — the API ships
the per-sentence claim mapping and a compact retrieval reasoning.
"""

import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api as api
from app.api import app, get_session
from app.db_models import Base

STORY = {
    "n": 1,
    "story_id": 5,
    "title": "Strikes resume along the border",
    "gist": "Cross-border strikes after the truce.",
    "sources": ["Reuters"],
    "corroboration": 0.8,
    "contested": False,
    "retrieval": "semantic",
    "relevance": 0.8,
}

ANSWER = "Strikes resumed at the border [1]. My read is escalation continues regardless."


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


def _fake_context(session, question=None, history=None, trace=None):
    if trace is not None:
        trace.update({"method": "semantic", "intents": ["conflict"], "terms": ["war", "back"]})
    return {"stories": [STORY]}


def test_ask_ships_claims_and_reasoning(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(api.qa, "build_qa_context", _fake_context)
    monkeypatch.setattr(api.client, "generate_json", lambda prompt, **kw: {"answer": ANSWER})

    body = client.post("/brain/ask", json={"question": "is the war back on?"}).json()
    app.dependency_overrides.clear()

    assert body["answer"] == ANSWER
    supported = [c["supported"] for c in body["claims"]]
    assert supported == [True, False]  # the "my read" sentence is brain analysis
    assert body["claims"][1]["matched_story"] is None
    assert body["reasoning"] == {
        "method": "semantic",
        "intents": ["conflict"],
        "terms": ["war", "back"],
    }


def test_busy_and_offline_have_empty_chip_fuel(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 100)
    monkeypatch.setattr(api.settings, "qa_min_free_mb", 3800)
    body = client.post("/brain/ask", json={"question": "hi"}).json()
    assert body["claims"] == []
    assert body["reasoning"] is None
    app.dependency_overrides.clear()


def test_stream_final_ships_claims_and_reasoning(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(api.qa, "build_qa_context", _fake_context)
    monkeypatch.setattr(api.client, "generate_text_stream", lambda prompt, **kw: iter([ANSWER]))

    with client.stream(
        "POST", "/brain/ask/stream", json={"question": "is the war back on?"}
    ) as resp:
        text = "".join(resp.iter_text())
    app.dependency_overrides.clear()

    final = next(b for b in text.split("\n\n") if "event: final" in b)
    data = json.loads(final.split("data: ", 1)[1])
    assert [c["supported"] for c in data["claims"]] == [True, False]
    assert data["reasoning"]["method"] == "semantic"
