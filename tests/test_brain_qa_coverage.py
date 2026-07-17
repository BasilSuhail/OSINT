"""Coverage-bias context for Q&A (#413 roadmap item 7, #463).

Transparent bias: the model must be able to see how thin or skewed local
feed coverage is per country, and the prompt must demand the caveat.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.sources.rss_registry as rss_registry
from app.brain import qa
from app.db_models import Base, EventRow

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def _fresh_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _event(session, *, source, country, event_id, hours_ago=1):
    session.add(
        EventRow(
            source=source,
            source_event_id=event_id,
            occurred_at=NOW - timedelta(hours=hours_ago),
            fetched_at=NOW,
            category="conflict",
            payload={"title": event_id},
            country=country,
        )
    )
    session.commit()


def test_coverage_counts_events_sources_and_share(monkeypatch):
    session = _fresh_session()
    monkeypatch.setattr(rss_registry, "content_owner_map", lambda: {})
    _event(session, source="reuters", country="IR", event_id="e1")
    _event(session, source="aj", country="IR", event_id="e2")
    _event(session, source="bbc", country="PH", event_id="e3")

    out = qa.build_coverage_bias(session, now=NOW)

    assert out["window_h"] == 72
    assert out["total_events"] == 3
    iran, ph = out["countries"]
    assert iran == {
        "country": "IR",
        "events": 2,
        "share": 0.667,
        "sources": 2,
        "owners": 2,
        "thin": True,
    }
    assert ph["country"] == "PH" and ph["sources"] == 1


def test_coverage_collapses_syndicated_owners(monkeypatch):
    # Three feeds, but two carry the same owner's words: owners=2 → still thin;
    # syndication must never inflate independence.
    session = _fresh_session()
    monkeypatch.setattr(
        rss_registry,
        "content_owner_map",
        lambda: {"yahoo": "reuters", "reuters": "reuters", "aj": "aj"},
    )
    _event(session, source="reuters", country="IR", event_id="e1")
    _event(session, source="yahoo", country="IR", event_id="e2")
    _event(session, source="aj", country="IR", event_id="e3")

    out = qa.build_coverage_bias(session, now=NOW)

    iran = out["countries"][0]
    assert iran["sources"] == 3
    assert iran["owners"] == 2
    assert iran["thin"] is True


def test_coverage_not_thin_with_three_owners(monkeypatch):
    session = _fresh_session()
    monkeypatch.setattr(rss_registry, "content_owner_map", lambda: {})
    for i, source in enumerate(("reuters", "aj", "bbc")):
        _event(session, source=source, country="IR", event_id=f"e{i}")

    out = qa.build_coverage_bias(session, now=NOW)

    assert out["countries"][0]["thin"] is False


def test_coverage_skips_countryless_and_stale_events(monkeypatch):
    session = _fresh_session()
    monkeypatch.setattr(rss_registry, "content_owner_map", lambda: {})
    _event(session, source="usgs", country=None, event_id="quake")
    _event(session, source="reuters", country="IR", event_id="old", hours_ago=100)

    out = qa.build_coverage_bias(session, now=NOW)

    assert out["total_events"] == 0
    assert out["countries"] == []


def test_coverage_caps_country_list(monkeypatch):
    session = _fresh_session()
    monkeypatch.setattr(rss_registry, "content_owner_map", lambda: {})
    for i in range(10):
        _event(session, source="reuters", country=f"C{i}", event_id=f"e{i}")

    out = qa.build_coverage_bias(session, now=NOW)

    assert len(out["countries"]) == 8
    assert out["total_events"] == 10


def test_qa_context_and_prompt_carry_coverage(monkeypatch):
    session = _fresh_session()
    monkeypatch.setattr(rss_registry, "content_owner_map", lambda: {})
    _event(session, source="reuters", country="IR", event_id="e1")

    ctx = qa.build_qa_context(session, now=NOW)
    assert ctx["coverage"]["countries"][0]["country"] == "IR"

    prompt = qa.build_qa_prompt(ctx, "what happened in Iran?")
    assert "CONTEXT.coverage" in prompt
    assert "coverage is thin" in prompt
    assert qa.build_qa_text_prompt(ctx, "what happened in Iran?").count("CONTEXT.coverage") == 1
