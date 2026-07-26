"""GET /stories/developing — the Situation card's pinned slot (#449)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import app, get_session
from app.db_models import (
    Base,
    EventRow,
    StoryCorroborationRow,
    StoryMemberRow,
    StoryRow,
)


def _seed(session: Session, *, title: str, severity: float, countries: tuple[str, ...]) -> int:
    now = datetime.now(UTC)
    story = StoryRow(
        title=title,
        first_seen=now - timedelta(hours=48),
        last_seen=now - timedelta(hours=1),
        member_count=len(countries),
        outlet_count=len(countries),
        owner_count=len(countries),
        method_version="stories-v1.0",
    )
    session.add(story)
    session.flush()
    for i, country in enumerate(countries):
        event = EventRow(
            source="rss",
            source_event_id=f"{title}-{i}",
            occurred_at=now - timedelta(hours=2),
            category="news",
            severity=severity,
            country=country,
            payload={"title": f"{title} {country}"},
        )
        session.add(event)
        session.flush()
        session.add(
            StoryMemberRow(
                event_id=event.id,
                story_id=story.id,
                similarity=0.5,
                added_at=now - timedelta(hours=2),
            )
        )
    session.flush()
    return story.id


def _client(seed) -> TestClient:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as s:
        seed(s)
        s.commit()

    def override():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def test_pinned_story_carries_reasons_and_corroboration() -> None:
    def seed(s: Session) -> None:
        sid = _seed(s, title="widening exchange", severity=0.6, countries=("IR", "UA", "RO"))
        s.add(
            StoryCorroborationRow(
                story_id=sid,
                score=0.62,
                components={"owners": 3},
                method_version="corroboration-v1.0",
            )
        )

    client = _client(seed)
    try:
        res = client.get("/stories/developing")
        assert res.status_code == 200
        body = res.json()
        assert len(body) == 1
        row = body[0]
        assert row["title"] == "widening exchange"
        assert row["outlet_count"] == 3
        assert row["owner_count"] == 3
        assert row["corroboration"] == 0.62
        assert row["pin_reasons"]["countries"] == 3
        assert row["pin_reasons"]["max_severity"] == 0.6
        assert row["pin_reasons"]["new_members_12h"] == 3
        assert row["pin_reasons"]["age_hours"] == 48
    finally:
        app.dependency_overrides.clear()


def test_nothing_developing_returns_empty_list() -> None:
    def seed(s: Session) -> None:
        _seed(s, title="stage win", severity=0.3, countries=("FR", "BE", "ES"))

    client = _client(seed)
    try:
        res = client.get("/stories/developing")
        assert res.status_code == 200
        assert res.json() == []
    finally:
        app.dependency_overrides.clear()


def test_limit_is_capped() -> None:
    def seed(s: Session) -> None:
        for i in range(5):
            _seed(s, title=f"story {i}", severity=0.7, countries=("IR", "UA", "RO"))

    client = _client(seed)
    try:
        assert len(client.get("/stories/developing?limit=2").json()) == 2
        assert client.get("/stories/developing?limit=99").status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_ordering_follows_selector_not_fetch_order() -> None:
    """The route must return rows in the selector's rank order, not DB fetch
    order. Seed the weak story first (fewer members => lower velocity and
    fewer countries) and the strong one second, so insertion/id order and
    selector order disagree — a route that iterated the fetched `stories`
    mapping instead of the selector's `order` map would return them
    insertion-first and fail this assertion (#449 review finding)."""

    def seed(s: Session) -> None:
        _seed(s, title="weak signal", severity=0.7, countries=("IR", "UA", "RO"))
        _seed(
            s,
            title="strong signal",
            severity=0.7,
            countries=("IR", "UA", "RO", "PK", "EG"),
        )

    client = _client(seed)
    try:
        res = client.get("/stories/developing")
        assert res.status_code == 200
        body = res.json()
        assert len(body) == 2
        assert body[0]["title"] == "strong signal"
        assert body[1]["title"] == "weak signal"
    finally:
        app.dependency_overrides.clear()
