"""Which story an event belongs to, asked once for a whole map selection (#782).

The map holds both kinds of row. A headline came from a feed and belongs to a
story; a GDELT record or a seismometer reading does not. This endpoint is what
lets a row know which it is, so news opens the story view and telemetry keeps
the evidence card.
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import app, get_session
from app.db_models import (
    Base,
    EventRow,
    StoryCorroborationRow,
    StoryMemberRow,
    StoryRow,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _client():
    """Two feed articles in one story, plus a GDELT row that is in none."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    ids: dict[str, int] = {}
    with factory() as s:
        story = StoryRow(
            title="Two villages evacuated as wildfire jumps the ridge",
            first_seen=NOW - timedelta(hours=6),
            last_seen=NOW,
            member_count=2,
            outlet_count=2,
            owner_count=2,
            method_version="stories-v1.0",
        )
        s.add(story)
        s.flush()
        s.add(
            StoryCorroborationRow(
                story_id=story.id, score=0.75, components={}, method_version="corroboration-v1.0"
            )
        )
        for i, source in enumerate(["rss-bbc", "rss-reuters"]):
            ev = EventRow(
                source=source,
                source_event_id=f"n{i}",
                occurred_at=NOW - timedelta(minutes=i),
                fetched_at=NOW,
                category="hazard",
                payload={"title": f"telling {i}"},
            )
            s.add(ev)
            s.flush()
            ids[source] = ev.id
            s.add(StoryMemberRow(event_id=ev.id, story_id=story.id, similarity=0.9))
        loose = EventRow(
            source="gdelt",
            source_event_id="g1",
            occurred_at=NOW,
            fetched_at=NOW,
            category="conflict",
            payload={"action_label": "Make statement"},
        )
        s.add(loose)
        s.flush()
        ids["gdelt"] = loose.id
        s.commit()

    app.dependency_overrides[get_session] = lambda: factory()
    return TestClient(app), ids


def _ids(*values: int) -> str:
    return ",".join(str(v) for v in values)


def test_feed_events_carry_their_story():
    client, ids = _client()
    r = client.get("/stories/for-events", params={"ids": _ids(ids["rss-bbc"], ids["rss-reuters"])})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {str(ids["rss-bbc"]), str(ids["rss-reuters"])}
    #: Both tellings resolve to the one story — that is what makes it a story.
    assert body[str(ids["rss-bbc"])]["id"] == body[str(ids["rss-reuters"])]["id"]


def test_payload_matches_what_a_first_page_row_shows():
    client, ids = _client()
    body = client.get("/stories/for-events", params={"ids": _ids(ids["rss-bbc"])}).json()
    story = body[str(ids["rss-bbc"])]
    assert story["owner_count"] == 2
    assert story["corroboration"] == 0.75
    assert story["title"] == "Two villages evacuated as wildfire jumps the ridge"


def test_telemetry_is_absent_rather_than_null():
    """A GDELT row has no story, and saying so by omission keeps the client's
    test a presence check rather than a null check."""
    client, ids = _client()
    body = client.get("/stories/for-events", params={"ids": _ids(ids["gdelt"])}).json()
    assert body == {}


def test_mixed_selection_answers_only_for_the_news():
    client, ids = _client()
    body = client.get(
        "/stories/for-events", params={"ids": _ids(ids["gdelt"], ids["rss-bbc"])}
    ).json()
    assert list(body) == [str(ids["rss-bbc"])]


def test_junk_ids_are_dropped_not_fatal():
    """The query string is built by a client that may have lost a row mid-render.
    A malformed id is not a reason to fail the whole selection."""
    client, ids = _client()
    body = client.get("/stories/for-events", params={"ids": f"abc,,{ids['rss-bbc']},-1"}).json()
    assert list(body) == [str(ids["rss-bbc"])]


def test_no_ids_is_an_empty_answer_not_a_scan():
    client, _ = _client()
    assert client.get("/stories/for-events", params={"ids": ""}).json() == {}
