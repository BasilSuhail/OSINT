"""On-demand LLM deep read of a contested story (#607).

The deterministic framing block (#605) says HOW blocs differ; the deep read asks
the local model WHY, in prose, grounded strictly in the given headlines and
taking no side. Tests cover the pure prompt/bloc builders here; the endpoint
wiring (RAM gate, typed failures) is covered against a mocked client.
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api as api
from app.api import app, get_session
from app.brain import deepread
from app.db_models import Base


def _framing() -> dict:
    return {
        "blocs": [
            {"country": "RU", "articles": 3, "tone": "mostly negative", "terms": ["anti", "fail"]},
            {"country": "FR", "articles": 2, "tone": "neutral", "terms": ["deal", "exemption"]},
        ],
        "synthesis": {},
    }


def _members() -> list[dict]:
    return [
        {"origin_country": "RU", "outlet": "TASS", "title": "Brussels sanctions will fail"},
        {"origin_country": "RU", "outlet": "RT", "title": "Anti-Russia move backfires"},
        {"origin_country": "FR", "outlet": "France 24", "title": "EU reaches sanctions deal"},
        {"origin_country": "XX", "outlet": "Nowhere", "title": "Unrelated"},  # not in framing
    ]


# ---- bloc builder ------------------------------------------------------------


def test_deep_read_blocs_group_headlines_by_bloc_in_framing_order():
    blocs = deepread.deep_read_blocs(_members(), _framing())
    assert [b["country"] for b in blocs] == ["RU", "FR"]  # framing order, XX dropped
    ru = blocs[0]
    assert ru["tone"] == "mostly negative"
    assert ru["terms"] == ["anti", "fail"]
    assert any("TASS" in h and "fail" in h for h in ru["headlines"])
    assert len(ru["headlines"]) == 2


def test_deep_read_blocs_caps_headlines_per_bloc():
    members = [
        {"origin_country": "RU", "outlet": "o", "title": f"headline {i}"} for i in range(20)
    ] + [{"origin_country": "FR", "outlet": "o", "title": "fr"}]
    framing = {
        "blocs": [
            {"country": "RU", "articles": 20, "tone": "neutral", "terms": []},
            {"country": "FR", "articles": 1, "tone": "neutral", "terms": []},
        ],
        "synthesis": {},
    }
    blocs = deepread.deep_read_blocs(members, framing)
    assert len(blocs[0]["headlines"]) == deepread._HEADLINES_PER_BLOC


# ---- prompt builder ----------------------------------------------------------


def test_build_deep_read_prompt_is_neutral_grounded_and_carries_the_data():
    prompt = deepread.build_deep_read_prompt(
        "EU sanctions package", deepread.deep_read_blocs(_members(), _framing())
    )
    low = prompt.lower()
    # Neutral: takes no side.
    assert "no side" in low or "not take sides" in low or "take no side" in low
    # Grounded strictly in the given headlines, no invention.
    assert "only the headlines" in low or "only the provided" in low or "invent no" in low
    # Speculation about the WHY must be labelled, not stated as fact.
    assert "label" in low or "may " in low or "speculat" in low
    # The actual material is in the prompt.
    assert "EU sanctions package" in prompt
    assert "RU" in prompt and "FR" in prompt
    assert "TASS" in prompt


# ---- endpoint ----------------------------------------------------------------


def _client_and_story():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    app.dependency_overrides[get_session] = lambda: iter([factory()])
    return TestClient(app), factory


def test_deep_read_busy_when_ram_low(monkeypatch):
    client, _ = _client_and_story()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 100)
    monkeypatch.setattr(api.settings, "qa_min_free_mb", 3800)
    monkeypatch.setattr(api, "_framing_analysis", lambda members: _framing())
    monkeypatch.setattr(api, "_story_members", lambda session, sid: _members())
    monkeypatch.setattr(api, "_story_or_404", lambda session, sid: object())
    body = client.post("/stories/1/deep-read").json()
    assert "busy" in body["analysis"].lower()
    app.dependency_overrides.clear()


def test_deep_read_returns_plain_text_analysis(monkeypatch):
    # #609: generate as plain text (no format=json), so a token-capped answer is
    # just shorter valid prose — never a truncated-JSON parse error.
    client, _ = _client_and_story()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(api, "_story_members", lambda session, sid: _members())
    monkeypatch.setattr(api, "_framing_analysis", lambda members: _framing())
    monkeypatch.setattr(api, "_story_or_404", lambda session, sid: type("S", (), {"title": "t"})())
    seen = {}

    def fake_stream(prompt, **kw):
        seen["num_predict"] = kw.get("num_predict")
        yield "Russia frames it as failure. "
        yield "France frames it as routine."

    monkeypatch.setattr(api.client, "generate_text_stream", fake_stream)
    #: The JSON path must not be used at all.
    monkeypatch.setattr(
        api.client,
        "generate_json",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("deep read must not use JSON")),
    )
    body = client.post("/stories/1/deep-read").json()
    assert "Russia frames it as failure" in body["analysis"]
    assert "France frames it as routine" in body["analysis"]
    assert seen["num_predict"] == deepread.DEEP_READ_NUM_PREDICT
    app.dependency_overrides.clear()


def test_deep_read_offline_when_generation_raises(monkeypatch):
    client, _ = _client_and_story()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(api, "_story_members", lambda session, sid: _members())
    monkeypatch.setattr(api, "_framing_analysis", lambda members: _framing())
    monkeypatch.setattr(api, "_story_or_404", lambda session, sid: type("S", (), {"title": "t"})())

    def boom(prompt, **kw):
        raise RuntimeError("connection refused")
        yield  # pragma: no cover — make it a generator

    monkeypatch.setattr(api.client, "generate_text_stream", boom)
    body = client.post("/stories/1/deep-read").json()
    assert "offline" in body["analysis"].lower()
    app.dependency_overrides.clear()


def test_deep_read_none_when_not_contested(monkeypatch):
    client, _ = _client_and_story()
    monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(api, "_story_members", lambda session, sid: _members())
    monkeypatch.setattr(api, "_framing_analysis", lambda members: None)
    monkeypatch.setattr(api, "_story_or_404", lambda session, sid: type("S", (), {"title": "t"})())
    monkeypatch.setattr(
        api.client,
        "generate_text_stream",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no gen")),
    )
    body = client.post("/stories/1/deep-read").json()
    assert body["analysis"] is None
    app.dependency_overrides.clear()
