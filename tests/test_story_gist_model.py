from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db_models import Base, BrainNarrativeRow, StoryGistRow
from app.housekeeping import prune_story_gist


def _gist(**kw):
    base = {
        "story_id": 1,
        "gist": "g",
        "category": "other",
        "escalating": "unclear",
        "model": "m",
        "method_version": "enrich-v1.0",
    }
    base.update(kw)
    return StoryGistRow(**base)


def test_story_gist_unique_story_method_enforced():
    # The worker's ON CONFLICT (story_id, method_version) dedup depends on this
    # constraint existing at the ORM/create_all level — guard it explicitly.
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_gist())
        session.commit()
        session.add(_gist(gist="dup"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_table_args_not_cross_contaminated():
    # Regression: StoryGistRow was once spliced in before BrainNarrativeRow's
    # __table_args__, stealing its index and dropping the unique constraint.
    assert {i.name for i in BrainNarrativeRow.__table__.indexes} == {"brain_narrative_created_idx"}
    assert {i.name for i in StoryGistRow.__table__.indexes} == {"story_gist_created_idx"}
    uniques = [
        c for c in StoryGistRow.__table__.constraints if type(c).__name__ == "UniqueConstraint"
    ]
    assert any(set(c.columns.keys()) == {"story_id", "method_version"} for c in uniques)


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
