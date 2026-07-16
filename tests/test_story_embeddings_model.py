from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db_models import Base, StoryEmbeddingRow
from app.housekeeping import prune_story_embeddings


def _embedding(**kw):
    base = {
        "story_id": 1,
        "model": "nomic-embed-text",
        "method_version": "embed-v1.0",
        "vector": [0.1, 0.2, 0.3],
    }
    base.update(kw)
    return StoryEmbeddingRow(**base)


def test_story_embeddings_unique_story_method_enforced():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_embedding())
        session.commit()
        session.add(_embedding(vector=[9.9]))
        with pytest.raises(IntegrityError):
            session.commit()


def test_story_embeddings_vector_roundtrip():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_embedding(vector=[0.5, -0.25, 1.0]))
        session.commit()
        row = session.execute(select(StoryEmbeddingRow)).scalar_one()
        assert row.vector == [0.5, -0.25, 1.0]
        assert row.model == "nomic-embed-text"


def test_prune_story_embeddings_deletes_old():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 16, tzinfo=UTC)
    with Session(engine) as session:
        session.add_all(
            [
                _embedding(story_id=1, created_at=now - timedelta(days=31)),
                _embedding(story_id=2, created_at=now - timedelta(days=1)),
            ]
        )
        session.commit()
        deleted = prune_story_embeddings(session, now=now)
        session.commit()
        assert deleted == 1
        assert session.execute(select(StoryEmbeddingRow.story_id)).scalars().all() == [2]
