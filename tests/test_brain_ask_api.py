import json

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
    monkeypatch.setattr(
        api.client, "generate_json", lambda prompt, **kw: {"answer": "Border clashes."}
    )
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
    monkeypatch.setattr(api.settings, "qa_min_free_mb", 3800)
    called = {"model": False}

    def _should_not_call(prompt, **kw):
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

    def _boom(prompt, **kw):
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
    monkeypatch.setattr(api.client, "generate_json", lambda prompt, **kw: ["not", "a", "dict"])
    resp = client.post("/brain/ask", json={"question": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "The brain is not working right now."
    assert body["context_digest"] is None
    app.dependency_overrides.clear()


def test_ask_blank_answer_degrades_gracefully(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(api.client, "generate_json", lambda prompt, **kw: {"answer": "  "})
    body = client.post("/brain/ask", json={"question": "hi"}).json()
    assert body["answer"] == "The brain is not working right now."
    assert body["context_digest"] is None
    app.dependency_overrides.clear()


def test_ask_returns_sources_and_strips_bad_citations(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None, trace=None: {
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
        api.client, "generate_json", lambda prompt, **kw: {"answer": "Clashes [1]. See [9]."}
    )
    body = client.post("/brain/ask", json={"question": "what is happening?"}).json()
    assert len(body["sources"]) == 1 and body["sources"][0]["n"] == 1
    assert body["sources"][0]["outlets"] == ["Reuters"]
    assert "[9]" not in body["answer"]
    assert "[1]" in body["answer"]
    app.dependency_overrides.clear()


def test_ask_repairs_uncited_story_answer(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None, trace=None: {
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
    # Draft shares no content terms with the story → unsalvageable → repair runs.
    calls = iter(
        [{"answer": "Tensions are rising in the region."}, {"answer": "Border clashes [1]."}]
    )
    monkeypatch.setattr(api.client, "generate_json", lambda prompt, **kw: next(calls))

    body = client.post("/brain/ask", json={"question": "what is happening?"}).json()

    assert body["answer"] == "Border clashes [1]."
    app.dependency_overrides.clear()


def test_ask_falls_back_to_cited_story_after_failed_repair(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None, trace=None: {
            "stories": [
                {
                    "n": 1,
                    "story_id": 5,
                    "title": "Border clashes",
                    "sources": ["Reuters"],
                    "corroboration": 0.8,
                    "contested": False,
                    "retrieval": "semantic",
                    "relevance": 0.8,
                }
            ]
        },
    )
    monkeypatch.setattr(
        api.client,
        "generate_json",
        lambda prompt, **kw: {"answer": "Tensions are rising in the region."},
    )

    body = client.post("/brain/ask", json={"question": "what is happening?"}).json()

    # No template: the honest no-evidence sentence, with sources still listed.
    assert body["answer"] == api.qa.NO_EVIDENCE_ANSWER
    assert body["sources"][0]["n"] == 1
    app.dependency_overrides.clear()


def test_ask_busy_has_empty_sources(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 100)
    monkeypatch.setattr(api.settings, "qa_min_free_mb", 3800)
    body = client.post("/brain/ask", json={"question": "hi"}).json()
    assert body["sources"] == []
    app.dependency_overrides.clear()


def test_ask_threads_question_into_context_retrieval(monkeypatch):
    client = _client()
    captured = {}
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)

    def _context(session, question=None, history=None, trace=None):
        captured["question"] = question
        return {"stories": []}

    monkeypatch.setattr(api.qa, "build_qa_context", _context)
    monkeypatch.setattr(api.client, "generate_json", lambda prompt, **kw: {"answer": "No match."})
    body = client.post("/brain/ask", json={"question": "what about hormuz?"}).json()
    assert body["answer"] == "No match."
    assert body["sources"] == []
    assert captured["question"] == "what about hormuz?"
    app.dependency_overrides.clear()


def test_ask_stream_returns_sources_delta_and_final(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None, trace=None: {
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
        api.client,
        "generate_text_stream",
        lambda prompt, **kw: iter(["Border ", "clashes [1]."]),
    )

    with client.stream(
        "POST", "/brain/ask/stream", json={"question": "what is happening?"}
    ) as resp:
        text = "".join(resp.iter_text())

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "event: sources" in text
    assert "event: delta" in text
    assert "Border clashes [1]." in text
    app.dependency_overrides.clear()


def test_ask_stream_falls_back_when_uncited(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None, trace=None: {
            "stories": [
                {
                    "n": 1,
                    "story_id": 5,
                    "title": "Border clashes",
                    "sources": ["Reuters"],
                    "corroboration": 0.8,
                    "contested": False,
                    "retrieval": "semantic",
                    "relevance": 0.8,
                }
            ]
        },
    )
    monkeypatch.setattr(
        api.client,
        "generate_text_stream",
        lambda prompt, **kw: iter(["Tensions are rising in the region."]),
    )
    monkeypatch.setattr(
        api.client, "generate_json", lambda prompt, **kw: {"answer": "Still uncited."}
    )

    with client.stream(
        "POST", "/brain/ask/stream", json={"question": "what is happening?"}
    ) as resp:
        text = "".join(resp.iter_text())

    assert api.qa.NO_EVIDENCE_ANSWER in text
    assert "The retrieved story is:" not in text
    app.dependency_overrides.clear()


def test_ask_stream_busy_returns_final(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 100)
    monkeypatch.setattr(api.settings, "qa_min_free_mb", 3800)

    with client.stream("POST", "/brain/ask/stream", json={"question": "hi"}) as resp:
        text = "".join(resp.iter_text())

    assert "event: final" in text
    assert "Brain busy" in text
    app.dependency_overrides.clear()


def test_ask_uses_qa_model_and_evicts(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None, trace=None: {"stories": []},
    )
    captured = {}

    def _generate(prompt, *, model=None, keep_alive=None, num_predict=None):
        captured["model"] = model
        captured["keep_alive"] = keep_alive
        captured["num_predict"] = num_predict
        return {"answer": "No match."}

    monkeypatch.setattr(api.client, "generate_json", _generate)
    client.post("/brain/ask", json={"question": "hi"})
    assert captured["model"] == api.settings.qa_model
    assert captured["keep_alive"] == "0"
    app.dependency_overrides.clear()


def test_ask_gate_uses_qa_floor(monkeypatch):
    # 2000 MB is fine for 1.5b (old 1200 floor) but NOT for the 4b Q&A model.
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 2000)
    body = client.post("/brain/ask", json={"question": "hi"}).json()
    assert "busy" in body["answer"].lower()
    app.dependency_overrides.clear()


def test_ask_stream_uses_qa_model_and_evicts(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None, trace=None: {"stories": []},
    )
    captured = {}

    def _stream(prompt, *, model=None, keep_alive=None, num_predict=None):
        captured["model"] = model
        captured["keep_alive"] = keep_alive
        captured["num_predict"] = num_predict
        yield "No match."

    monkeypatch.setattr(api.client, "generate_text_stream", _stream)
    resp = client.post("/brain/ask/stream", json={"question": "hi"})
    assert resp.status_code == 200
    assert captured["model"] == api.settings.qa_model
    assert captured["keep_alive"] == "0"
    app.dependency_overrides.clear()


def test_ask_no_evidence_fallback_for_wrong_topic(monkeypatch):
    # Retrieval returned an unrelated story and the model can't cite: the old
    # fallback echoed the unrelated story as the answer; the split (#459) now
    # answers the no-answer sentence and demotes the story to closest_matches.
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None, trace=None: {
            "stories": [
                {
                    "n": 1,
                    "story_id": 5,
                    "title": "Border clashes",
                    "gist": None,
                    "sources": ["Reuters"],
                    "corroboration": 0.8,
                    "contested": False,
                    "sensor": {},
                    "retrieval": "fill",
                    "relevance": None,
                }
            ]
        },
    )
    monkeypatch.setattr(
        api.client, "generate_json", lambda prompt, **kw: {"answer": "Uncited text."}
    )
    body = client.post("/brain/ask", json={"question": "what about the typhoon?"}).json()
    assert body["answer"] == api.qa.NO_LOCAL_EVIDENCE_ANSWER
    assert body["sources"] == []
    assert [s["story_id"] for s in body["closest_matches"]] == [5]
    app.dependency_overrides.clear()


def test_ask_stream_no_evidence_fallback_for_wrong_topic(monkeypatch):
    # Same dynamic as test_ask_no_evidence_fallback_for_wrong_topic above, but
    # through the STREAM endpoint: retrieval returns an unrelated story and
    # neither the draft nor the citation-repair pass produces a valid citation,
    # so the honest no-answer fallback must win over echoing the unrelated
    # story as an answer — and the final event demotes it to closest_matches.
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None, trace=None: {
            "stories": [
                {
                    "n": 1,
                    "story_id": 5,
                    "title": "Border clashes",
                    "gist": None,
                    "sources": ["Reuters"],
                    "corroboration": 0.8,
                    "contested": False,
                    "sensor": {},
                    "retrieval": "fill",
                    "relevance": None,
                }
            ]
        },
    )
    monkeypatch.setattr(
        api.client,
        "generate_text_stream",
        lambda prompt, **kw: iter(["Uncited text."]),
    )
    monkeypatch.setattr(
        api.client, "generate_json", lambda prompt, **kw: {"answer": "Still uncited."}
    )

    with client.stream(
        "POST", "/brain/ask/stream", json={"question": "what about the typhoon?"}
    ) as resp:
        text = "".join(resp.iter_text())

    assert api.qa.NO_LOCAL_EVIDENCE_ANSWER in text
    assert "The retrieved story is" not in text
    final = next(b for b in text.split("\n\n") if "event: final" in b)
    final_data = json.loads(final.split("data: ", 1)[1])
    assert final_data["sources"] == []
    assert [s["story_id"] for s in final_data["closest_matches"]] == [5]
    app.dependency_overrides.clear()


def test_ask_passes_history_to_context_and_prompt(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    seen: dict = {}

    def fake_generate(prompt, **kw):
        seen["prompt"] = prompt
        return {"answer": "Anchored."}

    monkeypatch.setattr(api.client, "generate_json", fake_generate)
    body = client.post(
        "/brain/ask",
        json={
            "question": "what do u think that was?",
            "history": [{"question": "what about iran?", "answer": "US strikes on Iran."}],
        },
    ).json()
    assert body["answer"] == "Anchored."
    assert "RECENT CONVERSATION" in seen["prompt"]
    assert "what about iran?" in seen["prompt"]
    app.dependency_overrides.clear()


def test_ask_history_capped_at_three_exchanges():
    client = _client()
    exchange = {"question": "q", "answer": "a"}
    resp = client.post(
        "/brain/ask",
        json={"question": "q?", "history": [exchange] * 4},
    )
    assert resp.status_code == 422
    app.dependency_overrides.clear()


def test_ask_salvages_uncited_grounded_answer(monkeypatch):
    # The model's prose matches the retrieved story but lacks [n]: the answer
    # must keep the prose with an appended citation — no repair call, never
    # the fallback template (#446).
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None, trace=None: {
            "stories": [
                {
                    "n": 1,
                    "story_id": 10,
                    "title": "Trade ban on Israeli settlements is the latest test of EU unity",
                    "gist": "EU weighs a trade ban covering settlement goods.",
                    "sources": ["Al Jazeera English"],
                    "corroboration": 0.938,
                    "contested": True,
                    "sensor": {},
                }
            ]
        },
    )
    calls: list[str] = []

    def fake_generate(prompt, **kw):
        calls.append(prompt)
        return {"answer": "Yes, there is a trade ban on Israeli settlements under EU discussion."}

    monkeypatch.setattr(api.client, "generate_json", fake_generate)
    body = client.post("/brain/ask", json={"question": "is there a trade ban on israel?"}).json()
    assert body["answer"] == (
        "Yes, there is a trade ban on Israeli settlements under EU discussion. [1]"
    )
    assert len(calls) == 1  # no repair round-trip
    app.dependency_overrides.clear()


_ECHO_STORIES = {
    "stories": [
        {
            "n": 1,
            "story_id": 9,
            "title": "US completes series of strikes on Iran, third this week",
            "gist": "US strikes Iran a third time this week.",
            "sources": ["Al Jazeera English"],
            "corroboration": 0.9,
            "contested": False,
            "sensor": {},
        }
    ]
}

_ECHO_HISTORY = [
    {
        "question": "is the US attacking iran again?",
        "answer": (
            "Yes, the US is launching strikes on Iran again, "
            "with the third strike occurring this week [1]."
        ),
    }
]


def test_ask_regenerates_when_answer_echoes_history(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None, trace=None: _ECHO_STORIES,
    )
    calls = iter(
        [
            # first generation parrots the previous answer
            {
                "answer": (
                    "Yes, the US is launching strikes on Iran again, "
                    "with the third strike occurring this week [1]."
                )
            },
            # retry answers the actual question
            {"answer": "Three strikes so far — the third hit this week per CENTCOM [1]."},
        ]
    )
    seen_prompts: list[str] = []

    def fake_generate(prompt, **kw):
        seen_prompts.append(prompt)
        return next(calls)

    monkeypatch.setattr(api.client, "generate_json", fake_generate)
    body = client.post(
        "/brain/ask", json={"question": "how many attacks till now?", "history": _ECHO_HISTORY}
    ).json()
    assert body["answer"].startswith("Three strikes so far")
    assert len(seen_prompts) == 2
    assert "repeat" in seen_prompts[1].lower()
    app.dependency_overrides.clear()


def test_ask_keeps_echoing_answer_when_retry_fails(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        api.qa,
        "build_qa_context",
        lambda session, question=None, history=None, trace=None: _ECHO_STORIES,
    )
    echoing = {
        "answer": (
            "Yes, the US is launching strikes on Iran again, "
            "with the third strike occurring this week [1]."
        )
    }
    calls = {"n": 0}

    def fake_generate(prompt, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return echoing
        raise RuntimeError("retry failed")

    monkeypatch.setattr(api.client, "generate_json", fake_generate)
    body = client.post(
        "/brain/ask", json={"question": "how many attacks till now?", "history": _ECHO_HISTORY}
    ).json()
    # degrade gracefully: an echo beats an error
    assert "third" in body["answer"]
    app.dependency_overrides.clear()
