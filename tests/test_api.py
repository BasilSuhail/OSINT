from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import app, get_session
from app.db_models import EventRow, IngestHealthRow, ScoreRow


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _seed(session):
    now = datetime.now(UTC)
    session.add_all(
        [
            EventRow(
                source="gdelt",
                source_event_id="1",
                occurred_at=now,
                category="conflict",
                keywords=[],
                payload={},
            ),
            EventRow(
                source="opensky-adsb",
                source_event_id="2",
                occurred_at=now - timedelta(hours=1),
                category="aviation",
                keywords=[],
                payload={},
            ),
        ]
    )
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


def test_events_accepts_dashboard_analytics_limit(db_session):
    client = _client(db_session)
    resp = client.get("/events?limit=20000")
    assert resp.status_code == 200


def test_scores_accepts_dashboard_analytics_limit(db_session):
    client = _client(db_session)
    resp = client.get("/scores?limit=20000")
    assert resp.status_code == 200


def test_scores_rejects_limits_above_contract(db_session):
    client = _client(db_session)
    resp = client.get("/scores?limit=20001")
    assert resp.status_code == 422


def test_events_exclude_filter(db_session):
    client = _client(db_session)
    rows = client.get("/events?exclude=opensky-adsb").json()
    assert all(r["source"] != "opensky-adsb" for r in rows)


def test_ingest_health_returns_rows(db_session):
    db_session.add(IngestHealthRow(source="gdelt", day=date.today(), success_n=3, failure_n=1))
    db_session.commit()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    rows = client.get("/ingest-health").json()
    assert rows and rows[0]["source"] == "gdelt"
    assert rows[0]["success_n"] == 3 and rows[0]["failure_n"] == 1
    assert "day" in rows[0]


def test_scores_ordered_bucket_start_desc(db_session):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    db_session.add_all(
        [
            ScoreRow(
                country="US",
                bucket_start=now - timedelta(hours=2),
                bucket_length=timedelta(hours=1),
                score_name="cii_v1",
                score_value=0.1,
                components={},
                method_version="v1",
            ),
            ScoreRow(
                country="US",
                bucket_start=now,
                bucket_length=timedelta(hours=1),
                score_name="cii_v1",
                score_value=0.9,
                components={},
                method_version="v1",
            ),
        ]
    )
    db_session.commit()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    rows = client.get("/scores").json()
    starts = [r["bucket_start"] for r in rows]
    assert starts == sorted(starts, reverse=True)  # newest first


def test_events_fetched_since_catches_past_occurred_at(db_session):
    """fetched_since uses fetched_at; since uses occurred_at — they must be independent."""
    now = datetime.now(UTC)
    past = now - timedelta(days=5)
    two_min_ago = now - timedelta(minutes=2)

    db_session.add(
        EventRow(
            source="gdelt",
            source_event_id="news-old",
            occurred_at=past,
            fetched_at=now,
            category="news",
            keywords=[],
            payload={},
        )
    )
    db_session.commit()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    cutoff_iso = two_min_ago.isoformat()

    # fetched_since filter: should RETURN the row (fetched_at=now >= two_min_ago)
    rows_fetched = client.get("/events", params={"fetched_since": cutoff_iso}).json()
    assert any(r["source_event_id"] == "news-old" for r in rows_fetched), (
        "fetched_since filter should return rows with fetched_at >= cutoff"
    )

    # since filter: should NOT return the row (occurred_at=past < two_min_ago)
    rows_since = client.get("/events", params={"since": cutoff_iso}).json()
    assert not any(r["source_event_id"] == "news-old" for r in rows_since), (
        "since filter must exclude rows where occurred_at < cutoff"
    )


def test_events_country_filter(db_session):
    now = datetime.now(UTC)
    db_session.add_all(
        [
            EventRow(
                source="gdelt",
                source_event_id="us-1",
                occurred_at=now,
                category="conflict",
                country="US",
                keywords=[],
                payload={},
            ),
            EventRow(
                source="gdelt",
                source_event_id="gb-1",
                occurred_at=now - timedelta(seconds=1),
                category="conflict",
                country="GB",
                keywords=[],
                payload={},
            ),
        ]
    )
    db_session.commit()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    rows = client.get("/events?country=US").json()
    assert all(r["country"] == "US" for r in rows)
    assert any(r["source_event_id"] == "us-1" for r in rows)
    assert not any(r["source_event_id"] == "gb-1" for r in rows)


def test_event_coverage_returns_per_source_counts(db_session):
    now = datetime.now(UTC)
    db_session.add_all(
        [
            EventRow(
                source="eonet",
                source_event_id="ice",
                occurred_at=now,
                fetched_at=now,
                category="hazard",
                lat=70,
                lon=-40,
                keywords=[],
                payload={},
            ),
            EventRow(
                source="rss-bbc-world",
                source_event_id="news",
                occurred_at=now - timedelta(days=10),
                fetched_at=now,
                category="news",
                keywords=[],
                payload={},
            ),
            EventRow(
                source="rss-bbc-world",
                source_event_id="old-news",
                occurred_at=now - timedelta(days=40),
                fetched_at=now - timedelta(days=40),
                category="news",
                keywords=[],
                payload={},
            ),
        ]
    )
    db_session.commit()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    rows = client.get("/events/coverage?days=30").json()
    by_source = {r["source"]: r for r in rows}

    assert by_source["eonet"]["total"] == 1
    assert by_source["eonet"]["recent"] == 1
    assert by_source["eonet"]["geocoded"] == 1
    assert by_source["rss-bbc-world"]["total"] == 2
    assert by_source["rss-bbc-world"]["recent"] == 1
    assert by_source["rss-bbc-world"]["geocoded"] == 0
    assert by_source["eonet"]["latest_fetched_at"] is not None


def test_events_ordered_occurred_at_desc(db_session):
    now = datetime.now(UTC)
    db_session.add_all(
        [
            EventRow(
                source="gdelt",
                source_event_id="old",
                occurred_at=now - timedelta(hours=3),
                category="conflict",
                keywords=[],
                payload={},
            ),
            EventRow(
                source="gdelt",
                source_event_id="new",
                occurred_at=now,
                category="conflict",
                keywords=[],
                payload={},
            ),
        ]
    )
    db_session.commit()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    rows = client.get("/events").json()
    occurred_ats = [r["occurred_at"] for r in rows]
    assert occurred_ats == sorted(occurred_ats, reverse=True), "events must be newest-first"


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


def test_stream_emits_keepalive_ticks():
    from app.api import app

    app.state.event_source = lambda: iter([None, "3"])
    client = TestClient(app)
    with client.stream("GET", "/stream") as resp:
        assert resp.status_code == 200
        body = ""
        for chunk in resp.iter_text():
            body += chunk
            if "data: 3" in body:
                break
    assert ": keepalive" in body
    assert "data: 3" in body
