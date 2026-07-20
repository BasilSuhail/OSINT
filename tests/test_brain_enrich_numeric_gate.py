"""The enrich loop must not store a gist carrying figures its headlines lack (#514)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.brain import enrich
from app.db_models import Base, EventRow, StoryGistRow, StoryMemberRow, StoryRow

HEADLINE = "Magnitude 5.1 earthquake in central Peru leaves at least one dead and ten injured"
INVENTED = "A magnitude 5.1 earthquake struck central Peru, killing at least five and injuring ten."
GROUNDED = "A magnitude 5.1 earthquake struck central Peru, killing one and injuring ten."


def _factory_with_story(now):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as s:
        story = StoryRow(
            title="Peru earthquake",
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
            category="disaster",
            payload={"title": HEADLINE},
        )
        s.add(event)
        s.flush()
        s.add(StoryMemberRow(event_id=event.id, story_id=story.id, similarity=1.0))
        s.commit()
    return factory


def _prepare(monkeypatch, now, replies):
    """Wire a gate-open enrich run whose model returns `replies` in order."""
    factory = _factory_with_story(now)
    monkeypatch.setattr(enrich, "_session_factory", lambda: factory)
    monkeypatch.setattr(enrich.gate, "should_run", lambda session, now=None: (True, "ok"))
    monkeypatch.setattr(
        enrich.embeddings.client, "embed", lambda texts, **kw: [[0.1] for _ in texts]
    )
    prompts: list[str] = []

    def _generate(prompt):
        prompts.append(prompt)
        gist = replies[min(len(prompts) - 1, len(replies) - 1)]
        return {"gist": gist, "category": "disaster", "escalating": "unclear"}

    monkeypatch.setattr(enrich.client, "generate_json", _generate)
    return factory, prompts


def test_invented_figure_is_never_stored(monkeypatch):
    now = datetime.now(UTC)
    factory, prompts = _prepare(monkeypatch, now, [INVENTED])
    result = enrich._enrich_body(now=now)
    assert result["enriched"] == 0
    assert result["rejected_numeric"] == 1
    assert len(prompts) == 2  # one retry before giving up
    with factory() as s:
        assert s.execute(select(StoryGistRow)).first() is None


def test_retry_that_comes_back_grounded_is_stored(monkeypatch):
    now = datetime.now(UTC)
    factory, _ = _prepare(monkeypatch, now, [INVENTED, GROUNDED])
    result = enrich._enrich_body(now=now)
    assert result["enriched"] == 1
    assert result["rejected_numeric"] == 0
    with factory() as s:
        assert s.execute(select(StoryGistRow)).scalar_one().gist == GROUNDED


def test_grounded_gist_costs_no_extra_call(monkeypatch):
    now = datetime.now(UTC)
    _, prompts = _prepare(monkeypatch, now, [GROUNDED])
    result = enrich._enrich_body(now=now)
    assert result["enriched"] == 1
    assert len(prompts) == 1


def test_retry_prompt_names_the_invented_figures(monkeypatch):
    now = datetime.now(UTC)
    _, prompts = _prepare(monkeypatch, now, [INVENTED, GROUNDED])
    enrich._enrich_body(now=now)
    extra = prompts[1].replace(prompts[0], "")
    assert extra and "5" in extra


def test_rejected_story_is_retried_on_a_later_run(monkeypatch):
    # No row is written, so nothing marks the story done — the next pass tries
    # again, and a model that behaves the second time gets its gist stored.
    now = datetime.now(UTC)
    factory, _ = _prepare(monkeypatch, now, [INVENTED])
    assert enrich._enrich_body(now=now)["rejected_numeric"] == 1
    monkeypatch.setattr(
        enrich.client,
        "generate_json",
        lambda prompt: {"gist": GROUNDED, "category": "disaster", "escalating": "unclear"},
    )
    assert enrich._enrich_body(now=now)["enriched"] == 1
    with factory() as s:
        assert s.execute(select(StoryGistRow)).scalar_one().gist == GROUNDED


def test_build_gist_prompt_unchanged_without_rejects():
    titles = ["Border clashes reported"]
    assert enrich.build_gist_prompt(titles) == enrich.build_gist_prompt(titles, rejected=None)
