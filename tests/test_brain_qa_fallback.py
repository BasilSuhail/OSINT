"""Relevance-aware fallback split (#413 roadmap item 3, #459).

The deterministic fallback must never present an unrelated story as the
answer: with weak retrieval the answer switches to the no-answer mode and the
API moves the retrieved stories to a separate closest-matches list.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.api as api
from app.api import app, get_session
from app.brain import qa
from app.db_models import Base
from tests.test_brain_qa_semantic import _add_vector
from tests.test_brain_qa_stories import _add_story


def _story(retrieval, relevance, n=1):
    return {
        "n": n,
        "story_id": n,
        "title": f"Story {n}",
        "gist": None,
        "sources": ["Reuters"],
        "corroboration": 0.9,
        "contested": False,
        "sensor": {},
        "retrieval": retrieval,
        "relevance": relevance,
    }


def test_has_relevant_evidence_thresholds():
    assert qa.has_relevant_evidence([_story("semantic", 0.7)]) is True
    assert qa.has_relevant_evidence([_story("semantic", 0.4)]) is False
    assert qa.has_relevant_evidence([_story("keyword", 0.5)]) is True
    assert qa.has_relevant_evidence([_story("keyword", 0.2)]) is False
    assert qa.has_relevant_evidence([_story("fill", None)]) is False
    assert qa.has_relevant_evidence([]) is False
    #: One relevant story among weak ones is enough.
    assert qa.has_relevant_evidence([_story("fill", None), _story("semantic", 0.8, n=2)]) is True
    #: Stories without provenance (older callers) count as weak, not an error.
    assert qa.has_relevant_evidence([{"n": 1, "title": "bare"}]) is False


def test_no_evidence_answer_splits_on_relevance():
    assert qa.build_no_evidence_answer([]) == qa.REFUSAL_ANSWER
    assert qa.build_no_evidence_answer([_story("semantic", 0.7)]) == qa.NO_EVIDENCE_ANSWER
    assert qa.build_no_evidence_answer([_story("fill", None)]) == qa.NO_LOCAL_EVIDENCE_ANSWER
    assert qa.build_no_evidence_answer([_story("semantic", 0.3)]) == qa.NO_LOCAL_EVIDENCE_ANSWER


def test_no_local_evidence_answer_is_canned():
    assert qa.requires_citation(qa.NO_LOCAL_EVIDENCE_ANSWER, 3) is False
    assert qa.citation_compliant(qa.NO_LOCAL_EVIDENCE_ANSWER, 3) is True
    #: Repeating the honest no-answer sentence is correct, not an echo.
    assert qa.answer_echoes(qa.NO_LOCAL_EVIDENCE_ANSWER, qa.NO_LOCAL_EVIDENCE_ANSWER) is False


def _fresh_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_build_qa_stories_carries_semantic_and_fill_provenance(monkeypatch):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    with_vec = _add_story(
        session,
        now,
        title="Explosion on Qeshm",
        source="aj",
        source_event_id="v",
        outlet_count=2,
    )
    no_vec = _add_story(
        session,
        now,
        title="Loud unrelated story",
        source="bbc",
        source_event_id="f",
        outlet_count=20,
    )
    _add_vector(session, with_vec, [1.0, 0.0])
    monkeypatch.setattr(qa.client, "embed", lambda texts, **kw: [[1.0, 0.0]])

    out = qa.build_qa_stories(session, now=now, question="explosion?")

    by_id = {s["story_id"]: s for s in out}
    assert by_id[with_vec]["retrieval"] == "semantic"
    assert by_id[with_vec]["relevance"] == 1.0
    assert by_id[no_vec]["retrieval"] == "fill"
    assert by_id[no_vec]["relevance"] is None


def test_build_qa_stories_carries_keyword_fraction(monkeypatch):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    war_id = _add_story(
        session,
        now,
        title="War resumes at the border",
        source="reuters",
        source_event_id="w",
        outlet_count=3,
    )

    def boom(texts, **kw):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(qa.client, "embed", boom)

    out = qa.build_qa_stories(session, now=now, question="war border")

    assert [s["story_id"] for s in out] == [war_id]
    assert out[0]["retrieval"] == "keyword"
    assert out[0]["relevance"] == 1.0


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


def _ask_with_fallback(monkeypatch, stories):
    """Drive /brain/ask into the deterministic fallback with fixed stories."""
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None: {"stories": stories},
    )
    #: Uncited nonsense from draft AND repair → salvage fails → fallback.
    monkeypatch.setattr(
        api.client, "generate_json", lambda prompt, **kw: {"answer": "vague uncited prose"}
    )
    body = client.post("/brain/ask", json={"question": "is the war back on?"}).json()
    app.dependency_overrides.clear()
    return body


def test_ask_weak_retrieval_moves_stories_to_closest_matches(monkeypatch):
    body = _ask_with_fallback(monkeypatch, [_story("fill", None)])
    assert body["answer"] == qa.NO_LOCAL_EVIDENCE_ANSWER
    assert body["sources"] == []
    assert [s["story_id"] for s in body["closest_matches"]] == [1]


def test_ask_relevant_retrieval_keeps_stories_as_sources(monkeypatch):
    body = _ask_with_fallback(monkeypatch, [_story("semantic", 0.8)])
    assert body["answer"] == qa.NO_EVIDENCE_ANSWER
    assert [s["story_id"] for s in body["sources"]] == [1]
    assert body["closest_matches"] == []


def test_ask_happy_path_has_empty_closest_matches(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(api.client, "generate_json", lambda prompt, **kw: {"answer": "All quiet."})
    body = client.post("/brain/ask", json={"question": "anything new?"}).json()
    app.dependency_overrides.clear()
    assert body["answer"] == "All quiet."
    assert body["closest_matches"] == []
