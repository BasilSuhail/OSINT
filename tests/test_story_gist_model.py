from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db_models import Base, StoryGistRow
from app.housekeeping import prune_story_gist


def test_story_gist_roundtrip():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            StoryGistRow(
                story_id=1,
                gist="Border clashes reported along a disputed frontier.",
                category="conflict",
                escalating="yes",
                model="qwen2.5:1.5b-instruct-q4_K_M",
                method_version="enrich-v1.0",
                created_at=datetime(2026, 7, 13, tzinfo=UTC),
            )
        )
        session.commit()
        row = session.execute(select(StoryGistRow)).scalar_one()
        assert row.category == "conflict"
        assert row.escalating == "yes"


def test_prune_story_gist_deletes_old():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 13, tzinfo=UTC)
    with Session(engine) as session:
        session.add_all(
            [
                StoryGistRow(
                    story_id=1,
                    gist="old",
                    category="other",
                    escalating="unclear",
                    model="m",
                    method_version="enrich-v1.0",
                    created_at=now - timedelta(days=31),
                ),
                StoryGistRow(
                    story_id=2,
                    gist="new",
                    category="other",
                    escalating="unclear",
                    model="m",
                    method_version="enrich-v1.0",
                    created_at=now - timedelta(days=1),
                ),
            ]
        )
        session.commit()
        deleted = prune_story_gist(session, now=now)
        session.commit()
        assert deleted == 1
        assert session.execute(select(StoryGistRow.gist)).scalars().all() == ["new"]
