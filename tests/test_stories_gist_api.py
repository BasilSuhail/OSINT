from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import app, get_session
from app.brain import enrich
from app.db_models import Base, StoryGistRow, StoryRow


def _client_and_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)

    def override():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    return TestClient(app), factory


def test_stories_top_includes_gist_when_present():
    client, factory = _client_and_factory()
    now = datetime.now(UTC)
    with factory() as s:
        story = StoryRow(
            title="Border clashes",
            first_seen=now - timedelta(hours=1),
            last_seen=now,
            member_count=2,
            outlet_count=2,
            owner_count=1,
            method_version="stories-v1.0",
        )
        s.add(story)
        s.flush()
        s.add(
            StoryGistRow(
                story_id=story.id,
                gist="Clashes at the frontier.",
                category="conflict",
                escalating="yes",
                model="m",
                method_version=enrich.METHOD_VERSION,
                created_at=now,
            )
        )
        s.commit()
    body = client.get("/stories/top").json()
    assert body[0]["gist"] == "Clashes at the frontier."
    assert body[0]["category"] == "conflict"
    assert body[0]["escalating"] == "yes"
    app.dependency_overrides.clear()


def test_stories_top_gist_null_when_absent():
    client, factory = _client_and_factory()
    now = datetime.now(UTC)
    with factory() as s:
        s.add(
            StoryRow(
                title="Quiet story",
                first_seen=now - timedelta(hours=1),
                last_seen=now,
                member_count=1,
                outlet_count=1,
                owner_count=1,
                method_version="stories-v1.0",
            )
        )
        s.commit()
    body = client.get("/stories/top").json()
    assert body[0]["gist"] is None
    assert body[0]["category"] is None
    app.dependency_overrides.clear()
