from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.brain import embeddings
from app.db_models import Base, EventRow, StoryEmbeddingRow, StoryGistRow, StoryMemberRow, StoryRow


def test_story_embed_text_composes_title_gist_keywords():
    text = embeddings.story_embed_text(
        title="Explosion heard on Iran's Qeshm island",
        gist="Multiple explosions reported near the Strait of Hormuz.",
        keywords=["iran", "explosion", "hormuz"],
    )
    assert "Explosion heard on Iran's Qeshm island" in text
    assert "Multiple explosions reported" in text
    assert "hormuz" in text


def test_story_embed_text_title_only_when_rest_missing():
    assert (
        embeddings.story_embed_text(title="Just a title", gist=None, keywords=[]) == "Just a title"
    )


def test_cosine_rank_orders_by_similarity():
    query = [1.0, 0.0]
    ranked = embeddings.cosine_rank(
        query,
        [
            (1, [0.0, 1.0]),  # orthogonal
            (2, [2.0, 0.0]),  # same direction, longer
            (3, [1.0, 1.0]),  # diagonal
        ],
    )
    assert [sid for sid, _ in ranked] == [2, 3, 1]
    assert ranked[0][1] == 1.0


def test_cosine_rank_zero_vector_scores_zero():
    ranked = embeddings.cosine_rank([1.0, 0.0], [(1, [0.0, 0.0])])
    assert ranked == [(1, 0.0)]


def _factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _seed_story(s: Session, *, title: str, gist: str | None = None, keywords=None) -> int:
    now = datetime(2026, 7, 16, tzinfo=UTC)
    story = StoryRow(method_version="story-v1", title=title, first_seen=now, last_seen=now)
    s.add(story)
    s.flush()
    if gist:
        s.add(
            StoryGistRow(
                story_id=story.id,
                gist=gist,
                category="other",
                escalating="unclear",
                model="m",
                method_version="enrich-v1.0",
            )
        )
    event = EventRow(
        source="gdelt",
        source_event_id=f"e{story.id}",
        occurred_at=now,
        fetched_at=now,
        category="conflict",
        keywords=keywords or [],
        payload={"title": title},
    )
    s.add(event)
    s.flush()
    s.add(StoryMemberRow(event_id=event.id, story_id=story.id, similarity=1.0))
    s.commit()
    return story.id


def test_embed_missing_stories_inserts_and_skips(monkeypatch):
    factory = _factory()
    with factory() as s:
        sid1 = _seed_story(
            s, title="Explosion on Qeshm", gist="Blasts near Hormuz", keywords=["iran"]
        )
        sid2 = _seed_story(s, title="World Cup semi-final")
        s.add(
            StoryEmbeddingRow(
                story_id=sid2,
                model="nomic-embed-text",
                method_version=embeddings.EMBED_METHOD_VERSION,
                vector=[0.5],
            )
        )
        s.commit()

    calls: list[list[str]] = []

    def fake_embed(texts, **kw):
        calls.append(texts)
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(embeddings.client, "embed", fake_embed)
    with factory() as s:
        counters = embeddings.embed_missing_stories(s, [sid1, sid2])
        rows = (
            s.execute(select(StoryEmbeddingRow).order_by(StoryEmbeddingRow.story_id))
            .scalars()
            .all()
        )

    assert counters == {"embedded": 1, "skipped_existing": 1, "failed": 0}
    assert len(calls) == 1 and len(calls[0]) == 1  # one batched call, only the missing story
    assert "Explosion on Qeshm" in calls[0][0]
    assert [r.story_id for r in rows] == sorted([sid1, sid2])


def test_embed_missing_stories_survives_embed_failure(monkeypatch):
    factory = _factory()
    with factory() as s:
        sid = _seed_story(s, title="A story")

    def boom(texts, **kw):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(embeddings.client, "embed", boom)
    with factory() as s:
        counters = embeddings.embed_missing_stories(s, [sid])
        rows = s.execute(select(StoryEmbeddingRow)).scalars().all()

    assert counters["failed"] == 1
    assert counters["embedded"] == 0
    assert rows == []
