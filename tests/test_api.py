from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import app, get_session
from app.db_models import EventRow


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _seed(session):
    now = datetime.now(UTC)
    session.add_all([
        EventRow(source="gdelt", source_event_id="1", occurred_at=now,
                 category="conflict", keywords=[], payload={}),
        EventRow(source="opensky-adsb", source_event_id="2",
                 occurred_at=now - timedelta(hours=1),
                 category="aviation", keywords=[], payload={}),
    ])
    session.commit()


def _client(db_session):
    _seed(db_session)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_health():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}


def test_events_returns_rows(db_session):
    client = _client(db_session)
    rows = client.get("/events").json()
    assert {r["source"] for r in rows} == {"gdelt", "opensky-adsb"}


def test_events_exclude_filter(db_session):
    client = _client(db_session)
    rows = client.get("/events?exclude=opensky-adsb").json()
    assert all(r["source"] != "opensky-adsb" for r in rows)


def test_stream_emits_ticks():
    from app.api import app
    app.state.event_source = lambda: iter(["3", "5"])
    client = TestClient(app)
    with client.stream("GET", "/stream") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = ""
        for chunk in resp.iter_text():
            body += chunk
            if "data: 5" in body:
                break
    assert "data: 3" in body and "data: 5" in body
