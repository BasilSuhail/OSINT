"""Over-refusal softening (#413 roadmap item 6, #467).

The #434 live failure: "did the ceasefire collapse?" refused despite three
relevant sources. When retrieval judged its stories relevant, a refusal is
the model contradicting its own context — retry once; keep the refusal if
the retry fails or still refuses (refusal beats invention).
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api as api
from app.api import app, get_session
from app.brain import qa
from app.db_models import Base

RELEVANT_STORY = {
    "n": 1,
    "story_id": 5,
    "title": "Ceasefire strained by cross-border strikes",
    "gist": "Strikes reported after the truce.",
    "sources": ["Reuters"],
    "corroboration": 0.8,
    "contested": False,
    "sensor": {},
    "retrieval": "semantic",
    "relevance": 0.8,
}

WEAK_STORY = {**RELEVANT_STORY, "retrieval": "fill", "relevance": None}


def test_refusal_retry_prompt_demands_caveated_answer():
    prompt = qa.build_refusal_retry_prompt({"stories": [RELEVANT_STORY]}, "q")
    assert "Do not refuse" in prompt
    assert "Partial evidence deserves a partial answer" in prompt
    assert qa.REFUSAL_ANSWER in prompt  # the honest escape hatch stays


def test_qa_prompt_allows_refusal_only_without_related_context():
    prompt = qa.build_qa_prompt({"stories": []}, "q")
    assert "Refuse ONLY when nothing in the context relates" in prompt
    assert "do not refuse" in prompt


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


def _ask(monkeypatch, story, answers):
    """POST /brain/ask with a scripted generate_json; returns (body, calls)."""
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None: {"stories": [story]},
    )
    calls: list[str] = []
    replies = iter(answers)

    def _generate(prompt, **kw):
        calls.append(prompt)
        return {"answer": next(replies)}

    monkeypatch.setattr(api.client, "generate_json", _generate)
    body = client.post("/brain/ask", json={"question": "did the ceasefire collapse?"}).json()
    app.dependency_overrides.clear()
    return body, calls


def test_refusal_with_relevant_evidence_retries_and_answers(monkeypatch):
    body, calls = _ask(
        monkeypatch,
        RELEVANT_STORY,
        [qa.REFUSAL_ANSWER, "Strikes strained the ceasefire; collapse is not confirmed [1]."],
    )
    assert body["answer"] == "Strikes strained the ceasefire; collapse is not confirmed [1]."
    assert len(calls) == 2
    assert "Do not refuse" in calls[1]


def test_refusal_with_weak_evidence_stays_without_retry(monkeypatch):
    body, calls = _ask(monkeypatch, WEAK_STORY, [qa.REFUSAL_ANSWER])
    assert body["answer"] == qa.REFUSAL_ANSWER
    assert len(calls) == 1  # no retry: the refusal was plausible


def test_retry_that_still_refuses_keeps_refusal(monkeypatch):
    body, calls = _ask(monkeypatch, RELEVANT_STORY, [qa.REFUSAL_ANSWER, qa.REFUSAL_ANSWER])
    assert body["answer"] == qa.REFUSAL_ANSWER
    assert len(calls) == 2


def test_retry_failure_keeps_refusal(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None: {"stories": [RELEVANT_STORY]},
    )
    calls: list[str] = []

    def _generate(prompt, **kw):
        calls.append(prompt)
        if len(calls) == 1:
            return {"answer": qa.REFUSAL_ANSWER}
        raise RuntimeError("ollama down")

    monkeypatch.setattr(api.client, "generate_json", _generate)
    body = client.post("/brain/ask", json={"question": "did the ceasefire collapse?"}).json()
    app.dependency_overrides.clear()
    assert body["answer"] == qa.REFUSAL_ANSWER
    assert len(calls) == 2


def test_non_refusal_answers_never_trigger_retry(monkeypatch):
    body, calls = _ask(monkeypatch, RELEVANT_STORY, ["The ceasefire held overnight [1]."])
    assert body["answer"] == "The ceasefire held overnight [1]."
    assert len(calls) == 1


def test_stream_endpoint_derefuses_too(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None: {"stories": [RELEVANT_STORY]},
    )
    monkeypatch.setattr(
        api.client,
        "generate_text_stream",
        lambda prompt, **kw: iter([qa.REFUSAL_ANSWER]),
    )
    monkeypatch.setattr(
        api.client,
        "generate_json",
        lambda prompt, **kw: {"answer": "Strikes strained the ceasefire [1]."},
    )

    with client.stream(
        "POST", "/brain/ask/stream", json={"question": "did the ceasefire collapse?"}
    ) as resp:
        text = "".join(resp.iter_text())

    app.dependency_overrides.clear()
    assert "Strikes strained the ceasefire [1]." in text
