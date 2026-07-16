from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.brain import enrich
from app.db_models import Base, EventRow, StoryGistRow, StoryMemberRow, StoryRow


def _factory_with_story(now):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as s:
        story = StoryRow(
            title="Border clashes reported",
            first_seen=now - timedelta(hours=2),
            last_seen=now,
            member_count=1,
            outlet_count=1,
            owner_count=1,
            method_version="stories-v1.0",
        )
        s.add(story)
        s.flush()
        event = EventRow(
            source="gdelt",
            source_event_id="e1",
            occurred_at=now,
            fetched_at=now,
            category="conflict",
            payload={"title": "Border clashes reported along frontier"},
        )
        s.add(event)
        s.flush()
        s.add(StoryMemberRow(event_id=event.id, story_id=story.id, similarity=1.0))
        s.commit()
    return factory


def test_enrich_persists_one_gist_per_story(monkeypatch):
    now = datetime.now(UTC)
    factory = _factory_with_story(now)
    monkeypatch.setattr(enrich, "_session_factory", lambda: factory)
    monkeypatch.setattr(enrich.gate, "should_run", lambda session, now=None: (True, "ok"))
    monkeypatch.setattr(
        enrich.client,
        "generate_json",
        lambda prompt: {"gist": "Clashes.", "category": "conflict", "escalating": "yes"},
    )
    result = enrich._enrich_body(now=now)
    assert result["enriched"] == 1
    with factory() as s:
        row = s.execute(select(StoryGistRow)).scalar_one()
        assert row.category == "conflict"
    # idempotent: a second run enriches nothing new
    result2 = enrich._enrich_body(now=now)
    assert result2["enriched"] == 0
    assert result2["skipped_existing"] == 1


def test_enrich_skips_when_gated(monkeypatch):
    now = datetime.now(UTC)
    factory = _factory_with_story(now)
    monkeypatch.setattr(enrich, "_session_factory", lambda: factory)
    monkeypatch.setattr(enrich.gate, "should_run", lambda session, now=None: (False, "low RAM"))
    result = enrich._enrich_body(now=now)
    assert result["enriched"] == 0
    assert result.get("reason") == "low RAM"
    with factory() as s:
        assert s.execute(select(StoryGistRow)).first() is None


def test_enrich_failed_story_does_not_abort_batch(monkeypatch):
    now = datetime.now(UTC)
    factory = _factory_with_story(now)
    monkeypatch.setattr(enrich, "_session_factory", lambda: factory)
    monkeypatch.setattr(enrich.gate, "should_run", lambda session, now=None: (True, "ok"))

    def _boom(prompt):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(enrich.client, "generate_json", _boom)
    result = enrich._enrich_body(now=now)
    assert result["failed"] == 1
    assert result["enriched"] == 0


def test_enrich_embeds_window_stories(monkeypatch):
    now = datetime.now(UTC)
    factory = _factory_with_story(now)
    monkeypatch.setattr(enrich, "_session_factory", lambda: factory)
    monkeypatch.setattr(enrich.gate, "should_run", lambda session, now=None: (True, "ok"))
    monkeypatch.setattr(
        enrich.client,
        "generate_json",
        lambda prompt: {"gist": "Clashes.", "category": "conflict", "escalating": "yes"},
    )
    monkeypatch.setattr(
        enrich.embeddings.client, "embed", lambda texts, **kw: [[0.1] for _ in texts]
    )
    result = enrich._enrich_body(now=now)
    assert result["embedded"] == 1
    from app.db_models import StoryEmbeddingRow

    with factory() as s:
        row = s.execute(select(StoryEmbeddingRow)).scalar_one()
        assert row.vector == [0.1]
    # idempotent second run
    result2 = enrich._enrich_body(now=now)
    assert result2["embedded"] == 0


def test_enrich_embed_failure_never_fails_job(monkeypatch):
    now = datetime.now(UTC)
    factory = _factory_with_story(now)
    monkeypatch.setattr(enrich, "_session_factory", lambda: factory)
    monkeypatch.setattr(enrich.gate, "should_run", lambda session, now=None: (True, "ok"))
    monkeypatch.setattr(
        enrich.client,
        "generate_json",
        lambda prompt: {"gist": "Clashes.", "category": "conflict", "escalating": "yes"},
    )

    def _boom(texts, **kw):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(enrich.embeddings.client, "embed", _boom)
    result = enrich._enrich_body(now=now)
    assert result["enriched"] == 1
    assert result["embed_failed"] == 1
