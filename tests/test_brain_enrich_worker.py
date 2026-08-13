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


def _factory_with_two_stories(now):
    """A widely-told story whose latest filing is older than a singleton's."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as s:
        for title, owners, age_minutes in (
            ("Told by twenty owners", 20, 60),
            ("Told once, filed a minute ago", 1, 1),
        ):
            story = StoryRow(
                title=title,
                first_seen=now - timedelta(hours=3),
                last_seen=now - timedelta(minutes=age_minutes),
                member_count=owners,
                outlet_count=owners,
                owner_count=owners,
                method_version="stories-v1.0",
            )
            s.add(story)
            s.flush()
            event = EventRow(
                source="gdelt",
                source_event_id=f"e-{owners}",
                occurred_at=now - timedelta(minutes=age_minutes),
                fetched_at=now,
                category="news",
                payload={"title": title},
            )
            s.add(event)
            s.flush()
            s.add(StoryMemberRow(event_id=event.id, story_id=story.id, similarity=1.0))
        s.commit()
    return factory


def test_the_budget_goes_to_the_widely_told_story_first(monkeypatch):
    # The window holds thousands of single-filing stories against a few dozen
    # big ones, so ordering on recency alone spent the batch on whatever
    # arrived last and left the stories a reader opens with no tag (#926).
    now = datetime.now(UTC)
    factory = _factory_with_two_stories(now)
    monkeypatch.setattr(enrich, "_session_factory", lambda: factory)
    monkeypatch.setattr(enrich.gate, "should_run", lambda session, now=None: (True, "ok"))
    monkeypatch.setattr(
        enrich.client,
        "generate_json",
        lambda prompt: {"gist": "A summary.", "category": "conflict", "escalating": "no"},
    )
    result = enrich._enrich_body(now=now, batch_limit=1)
    assert result["enriched"] == 1
    with factory() as s:
        story_id = s.execute(select(StoryGistRow.story_id)).scalar_one()
        title = s.execute(select(StoryRow.title).where(StoryRow.id == story_id)).scalar_one()
    assert title == "Told by twenty owners"


def test_a_gist_from_a_retired_method_version_does_not_block_a_fresh_one(monkeypatch):
    # The row is keyed on (story_id, method_version) and inserted with
    # on_conflict_do_nothing, so before #948 a story tagged once was skipped on
    # every later pass — and the model swap in #926 reached only stories that
    # had never been tagged at all (#948).
    now = datetime.now(UTC)
    factory = _factory_with_story(now)
    with factory() as s:
        story_id = s.execute(select(StoryRow.id)).scalar_one()
        s.add(
            StoryGistRow(
                story_id=story_id,
                gist="Written by the retired model.",
                category="disaster",
                escalating="yes",
                model="a-retired-model",
                method_version="enrich-v1.0",
            )
        )
        s.commit()
    monkeypatch.setattr(enrich, "_session_factory", lambda: factory)
    monkeypatch.setattr(enrich.gate, "should_run", lambda session, now=None: (True, "ok"))
    monkeypatch.setattr(
        enrich.client,
        "generate_json",
        lambda prompt: {"gist": "Written afresh.", "category": "conflict", "escalating": "no"},
    )
    result = enrich._enrich_body(now=now)
    assert result["enriched"] == 1
    with factory() as s:
        current = s.execute(
            select(StoryGistRow.gist).where(StoryGistRow.method_version == enrich.METHOD_VERSION)
        ).scalar_one()
    assert current == "Written afresh."
