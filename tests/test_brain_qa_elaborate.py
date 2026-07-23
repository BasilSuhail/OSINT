"""Elaborate mode (#600): opt-in ELI10 answers with labeled inference.

Every answer is concise by default (good). When the reader asks to explain or
elaborate, the brain goes long — plain-words breakdown of the reporting, then a
clearly-flagged "what could come next" section that is the brain's own read,
never stated as fact.
"""

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api as api
from app.api import app, get_session
from app.brain import client, qa
from app.db_models import Base

# ---- trigger detection -------------------------------------------------------


def test_is_elaborate_request_detects_triggers():
    for q in (
        "elaborate on this",
        "explain the Mamdani story",
        "can you enhance that answer",
        "expand on that",
        "break this down for me",
        "tell me more",
        "go deeper",
        "ELI5 please",
        "in simple terms what happened",
        "explain it in detail",
    ):
        assert qa.is_elaborate_request(q), q


def test_is_elaborate_request_leaves_normal_questions_alone():
    for q in ("what is loudest right now?", "is Iran escalating?", "who struck first?"):
        assert not qa.is_elaborate_request(q), q


# ---- prompt shape ------------------------------------------------------------


def test_concise_prompt_is_the_default_and_unchanged():
    prompt = qa.build_qa_prompt({"stories": []}, "q")
    assert "ELABORATE MODE" not in prompt
    assert "short plain-English string" in prompt


def test_elaborate_prompt_overrides_brevity_with_structure():
    prompt = qa.build_qa_prompt({"stories": []}, "q", elaborate=True)
    assert "ELABORATE MODE" in prompt
    # ELI10 voice + the three-part structure.
    assert "10-year-old" in prompt
    assert "WHAT HAPPENED" in prompt
    assert "WHAT COULD COME NEXT" in prompt
    # The speculation section is flagged as the brain's own read, never fact.
    assert "my read, not reported" in prompt
    # No longer asks for a SHORT string.
    assert "short plain-English string" not in prompt


def test_elaborate_text_prompt_keeps_override_and_drops_json_wrapper():
    text = qa.build_qa_text_prompt({"stories": []}, "q", elaborate=True)
    assert "ELABORATE MODE" in text
    assert "Return a JSON object" not in text
    assert "Return only the final plain-English answer text" in text


# ---- token budget ------------------------------------------------------------


def test_generate_json_threads_num_predict(monkeypatch):
    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "{}"}

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: captured.update(json) or _Resp())
    client.generate_json("hi", num_predict=768)
    assert captured["options"]["num_predict"] == 768


def test_generate_json_omits_num_predict_by_default(monkeypatch):
    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "{}"}

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: captured.update(json) or _Resp())
    client.generate_json("hi")
    assert "num_predict" not in captured["options"]


# ---- endpoint wiring ---------------------------------------------------------


def _client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
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


def test_elaborate_ask_raises_the_token_cap(monkeypatch):
    client_ = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    seen: dict = {}

    def fake_generate(prompt, **kw):
        seen["num_predict"] = kw.get("num_predict")
        return {"answer": "Plain breakdown of the border clashes."}

    monkeypatch.setattr(api.client, "generate_json", fake_generate)
    client_.post("/brain/ask", json={"question": "explain the border clashes"})
    assert seen["num_predict"] == qa.ELABORATE_NUM_PREDICT


def test_elaborate_ask_skips_the_echo_guard(monkeypatch):
    client_ = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.client,
        "generate_json",
        lambda prompt, **kw: {"answer": "A much deeper take on the very same point [1]."},
    )
    monkeypatch.setattr(
        api,
        "_ask_sources",
        lambda stories, sensors=None: [{"n": 1, "story_id": 5, "title": "t"}],
    )

    def _must_not_run(*a, **k):
        raise AssertionError("echo guard must not run in elaborate mode")

    monkeypatch.setattr(api, "_deechoed_answer", _must_not_run)
    resp = client_.post(
        "/brain/ask",
        json={
            "question": "elaborate on that",
            "history": [{"question": "what happened?", "answer": "A point about the clashes [1]."}],
        },
    )
    assert resp.status_code == 200


def test_normal_ask_still_runs_the_echo_guard(monkeypatch):
    client_ = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.client, "generate_json", lambda prompt, **kw: {"answer": "Border clashes [1]."}
    )
    calls: list[int] = []
    real = api._deechoed_answer

    def _spy(answer, **kw):
        calls.append(1)
        return real(answer, **kw)

    monkeypatch.setattr(api, "_deechoed_answer", _spy)
    client_.post("/brain/ask", json={"question": "what is loudest?"})
    assert calls == [1]
