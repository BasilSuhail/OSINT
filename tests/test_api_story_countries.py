"""Where a story says it is, on the story payload (#919)."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import app, get_session
from app.db_models import Base, EventRow, StoryMemberRow, StoryRow

NOW = datetime.now(UTC)


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


def _story(session, title: str) -> StoryRow:
    story = StoryRow(
        title=title,
        first_seen=NOW - timedelta(hours=2),
        last_seen=NOW,
        member_count=0,
        outlet_count=1,
        owner_count=1,
        method_version="stories-v1.0",
    )
    session.add(story)
    session.flush()
    return story


def _member(session, story_id: int, event_id: int, country: str | None, source: str) -> None:
    session.add(
        EventRow(
            id=event_id,
            source=source,
            source_event_id=f"e{event_id}",
            occurred_at=NOW - timedelta(minutes=30),
            category="news",
            country=country,
            payload={"title": "a filing"},
        )
    )
    session.add(StoryMemberRow(event_id=event_id, story_id=story_id, similarity=0.9, added_at=NOW))


def test_countries_are_commonest_first():
    """Two filings place it in CO and one in IL, so it reads as a Colombian
    story that Israel also covered — not the other way round."""
    client, factory = _client_and_factory()
    with factory() as s:
        story = _story(s, "Colombia earthquake")
        _member(s, story.id, 1, "CO", "rss-a")
        _member(s, story.id, 2, "CO", "rss-b")
        _member(s, story.id, 3, "IL", "rss-jpost-world")
        s.commit()

    body = client.get("/stories/top").json()
    assert body[0]["countries"] == ["CO", "IL"]


def test_a_story_with_no_resolved_country_reports_an_empty_list():
    """Absent is "we do not know where", which the reader can be told. It must
    not be a missing key that a client has to guess about."""
    client, factory = _client_and_factory()
    with factory() as s:
        story = _story(s, "Unplaced filing")
        _member(s, story.id, 10, None, "rss-a")
        s.commit()

    body = client.get("/stories/top").json()
    assert body[0]["countries"] == []


def test_countries_do_not_leak_between_stories():
    client, factory = _client_and_factory()
    with factory() as s:
        first = _story(s, "Kenya debt talks")
        second = _story(s, "Pakistan court ruling")
        _member(s, first.id, 20, "KE", "rss-a")
        _member(s, second.id, 21, "PK", "rss-b")
        s.commit()

    by_title = {row["title"]: row["countries"] for row in client.get("/stories/top").json()}
    assert by_title["Kenya debt talks"] == ["KE"]
    assert by_title["Pakistan court ruling"] == ["PK"]
