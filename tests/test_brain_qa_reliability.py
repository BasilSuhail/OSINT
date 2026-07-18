"""Answer reliability fixes (#474).

The 2026-07-17 graded audit: 3/12 answers were "The brain is not working
right now." (unusable model output, no retry) and one truncated
mid-sentence. Operational messages also leaked into claim counting.
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api as api
from app.api import app, get_session
from app.brain import qa
from app.db_models import Base


def test_trim_incomplete_tail():
    assert qa.trim_incomplete_tail("All good here [1].") == "All good here [1]."
    #: The audit Q9 shape: complete sentence, then a token-limit fragment
    #: whose trailing citation must not disguise it as complete.
    truncated = "The chances are high [1]. The stories report that Iran and the US are [1]"
    assert qa.trim_incomplete_tail(truncated) == "The chances are high [1]."
    #: A lone fragment stays — something beats nothing.
    assert qa.trim_incomplete_tail("The stories report that") == "The stories report that"
    assert qa.trim_incomplete_tail("") == ""
    assert qa.trim_incomplete_tail("Really? Yes! Done.") == "Really? Yes! Done."


def test_check_claims_exempts_operational_answers():
    for message in qa.OPERATIONAL_ANSWERS:
        assert qa.check_claims(message, {1: "anything"}) == {"claims": [], "unsupported": 0}


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


def _ask_with_replies(monkeypatch, replies):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    calls: list[int] = []
    replies = iter(replies)

    def _generate(prompt, **kw):
        calls.append(1)
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(api.client, "generate_json", _generate)
    body = client.post("/brain/ask", json={"question": "anything new?"}).json()
    app.dependency_overrides.clear()
    return body, len(calls)


def test_ask_retries_unusable_output_once(monkeypatch):
    body, calls = _ask_with_replies(monkeypatch, [["not", "a", "dict"], {"answer": "All quiet."}])
    assert body["answer"] == "All quiet."
    assert calls == 2


def test_ask_blank_then_good_recovers(monkeypatch):
    body, calls = _ask_with_replies(monkeypatch, [{"answer": "  "}, {"answer": "All quiet."}])
    assert body["answer"] == "All quiet."
    assert calls == 2


def test_ask_two_unusable_outputs_report_not_working(monkeypatch):
    body, calls = _ask_with_replies(monkeypatch, [{"answer": ""}, ["still", "bad"]])
    assert body["answer"] == qa.BRAIN_NOT_WORKING_ANSWER
    assert calls == 2


def test_ask_retry_exception_reports_not_working(monkeypatch):
    body, calls = _ask_with_replies(monkeypatch, [{"answer": ""}, RuntimeError("ollama down")])
    assert body["answer"] == qa.BRAIN_NOT_WORKING_ANSWER
    assert calls == 2


def test_ask_good_output_never_retries(monkeypatch):
    body, calls = _ask_with_replies(monkeypatch, [{"answer": "All quiet."}])
    assert body["answer"] == "All quiet."
    assert calls == 1


def test_stream_empty_output_retries_via_json(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(api.client, "generate_text_stream", lambda prompt, **kw: iter([]))
    monkeypatch.setattr(
        api.client, "generate_json", lambda prompt, **kw: {"answer": "Recovered answer."}
    )

    with client.stream("POST", "/brain/ask/stream", json={"question": "anything new?"}) as resp:
        text = "".join(resp.iter_text())

    app.dependency_overrides.clear()
    assert "Recovered answer." in text
    assert qa.BRAIN_NOT_WORKING_ANSWER not in text


def test_stream_empty_output_and_failed_retry_reports_not_working(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(api.client, "generate_text_stream", lambda prompt, **kw: iter([]))

    def boom(prompt, **kw):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(api.client, "generate_json", boom)

    with client.stream("POST", "/brain/ask/stream", json={"question": "anything new?"}) as resp:
        text = "".join(resp.iter_text())

    app.dependency_overrides.clear()
    assert qa.BRAIN_NOT_WORKING_ANSWER in text


def test_checked_answer_trims_truncated_tail(monkeypatch):
    #: The trimmed fragment loses its citation; the surviving sentence keeps its
    #: own and stays compliant with no extra model call.
    def must_not_call(prompt, **kw):
        raise AssertionError("repair must not run for a compliant trimmed answer")

    monkeypatch.setattr(api.client, "generate_json", must_not_call)
    out = api._checked_ask_answer(
        answer="Strikes resumed at the border [1]. The stories report that Iran and the US are [1]",
        qa_context={"stories": []},
        question="q",
        stories=[{"n": 1, "story_id": 5, "title": "Strikes resume", "gist": None}],
        n_sources=1,
    )
    assert out == "Strikes resumed at the border [1]."
