from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.api as api
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
                payload={"title": "A headline"},
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


def test_api_allows_dev_frontend_origin(db_session):
    client = _client(db_session)
    resp = client.get("/health", headers={"Origin": "http://localhost:3001"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3001"


def test_events_returns_rows(db_session):
    client = _client(db_session)
    rows = client.get("/events").json()
    assert {r["source"] for r in rows} == {"gdelt", "opensky-adsb"}


def test_events_accepts_dashboard_analytics_limit(db_session):
    client = _client(db_session)
    resp = client.get("/events?limit=10000")
    assert resp.status_code == 200


def test_scores_accepts_dashboard_analytics_limit(db_session):
    client = _client(db_session)
    resp = client.get("/scores?limit=10000")
    assert resp.status_code == 200


def test_scores_rejects_limits_above_contract(db_session):
    client = _client(db_session)
    resp = client.get("/scores?limit=10001")
    assert resp.status_code == 422


def test_api_default_limit_never_exceeds_max_limit():
    assert api.API_DEFAULT_LIMIT <= api.API_MAX_LIMIT


def test_scores_filters_by_score_name_before_limit(db_session):
    now = datetime.now(UTC)
    db_session.add_all(
        [
            ScoreRow(
                country="US",
                bucket_start=now,
                bucket_length=timedelta(hours=1),
                score_name="other",
                score_value=0.1,
                components={},
                method_version="v1",
            ),
            ScoreRow(
                country="GB",
                bucket_start=now - timedelta(hours=1),
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

    rows = client.get("/scores?score_name=cii_v1&limit=1").json()
    assert len(rows) == 1
    assert rows[0]["score_name"] == "cii_v1"
    assert rows[0]["country"] == "GB"


def test_scores_filters_by_since_and_country(db_session):
    now = datetime.now(UTC)
    old = now - timedelta(days=3)
    db_session.add_all(
        [
            ScoreRow(
                country="US",
                bucket_start=now,
                bucket_length=timedelta(hours=1),
                score_name="cii_v1",
                score_value=0.7,
                components={},
                method_version="v1",
            ),
            ScoreRow(
                country="GB",
                bucket_start=now,
                bucket_length=timedelta(hours=1),
                score_name="cii_v1",
                score_value=0.8,
                components={},
                method_version="v1",
            ),
            ScoreRow(
                country="US",
                bucket_start=old,
                bucket_length=timedelta(hours=1),
                score_name="cii_v1",
                score_value=0.2,
                components={},
                method_version="v1",
            ),
        ]
    )
    db_session.commit()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    rows = client.get(
        "/scores",
        params={
            "score_name": "cii_v1",
            "country": "US",
            "since": (now - timedelta(days=1)).isoformat(),
        },
    ).json()
    assert len(rows) == 1
    assert rows[0]["country"] == "US"
    assert rows[0]["score_value"] == 0.7


def test_events_exclude_filter(db_session):
    client = _client(db_session)
    rows = client.get("/events?exclude=opensky-adsb").json()
    assert all(r["source"] != "opensky-adsb" for r in rows)


def test_ingest_health_returns_rows(db_session):
    db_session.add(
        IngestHealthRow(
            source="gdelt",
            day=date.today(),
            success_n=3,
            failure_n=1,
            new_data_n=2,
            unchanged_n=1,
            fetched_rows=40,
            accepted_rows=35,
            inserted_rows=12,
            rejected_rows=5,
            last_state="new_data",
            last_fetched=10,
            last_accepted=9,
            last_inserted=4,
            last_rejected=1,
        )
    )
    db_session.commit()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    rows = client.get("/ingest-health").json()
    assert rows and rows[0]["source"] == "gdelt"
    assert rows[0]["success_n"] == 3 and rows[0]["failure_n"] == 1
    assert rows[0]["last_state"] == "new_data"
    assert rows[0]["fetched_rows"] == 40
    assert rows[0]["accepted_rows"] == 35
    assert rows[0]["inserted_rows"] == 12
    assert rows[0]["rejected_rows"] == 5
    assert rows[0]["last_inserted"] == 4
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
    """Incremental timestamps remain independent from the event time."""
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
            payload={"title": "A headline"},
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

    rows_updated = client.get("/events", params={"updated_since": cutoff_iso}).json()
    updated = next(r for r in rows_updated if r["source_event_id"] == "news-old")
    assert updated["updated_at"] is not None

    # since filter: should NOT return the row (occurred_at=past < two_min_ago)
    rows_since = client.get("/events", params={"since": cutoff_iso}).json()
    assert not any(r["source_event_id"] == "news-old" for r in rows_since), (
        "since filter must exclude rows where occurred_at < cutoff"
    )


def test_events_updated_cursor_pages_equal_timestamps(db_session):
    """A limited page must not skip rows sharing one transaction timestamp."""
    revision = datetime.now(UTC)
    occurred_at = revision - timedelta(days=5)
    rows = [
        EventRow(
            source="cursor-source",
            source_event_id=f"cursor-{index}",
            occurred_at=occurred_at,
            fetched_at=revision,
            updated_at=revision,
            category="news",
            keywords=[],
            payload={},
        )
        for index in range(3)
    ]
    db_session.add_all(rows)
    db_session.commit()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    cutoff = (revision - timedelta(seconds=1)).isoformat()
    first = client.get(
        "/events",
        params={"updated_since": cutoff, "sources": "cursor-source", "limit": 2},
    ).json()
    assert len(first) == 2

    second = client.get(
        "/events",
        params={
            "updated_since": first[-1]["updated_at"],
            "updated_after_id": first[-1]["id"],
            "sources": "cursor-source",
            "limit": 2,
        },
    ).json()
    assert [row["id"] for row in first + second] == [str(row.id) for row in rows]


def test_events_viewport_recovers_local_rows_starved_by_global_limit(db_session):
    """A dense global feed must not decide what exists in a city viewport."""
    now = datetime.now(UTC)
    remote = [
        EventRow(
            source="viewport-test",
            source_event_id=f"remote-{index}",
            occurred_at=now - timedelta(minutes=index),
            category="news",
            lat=40.0,
            lon=-74.0,
            keywords=[],
            payload={},
        )
        for index in range(2)
    ]
    local = [
        EventRow(
            source="viewport-test",
            source_event_id=f"edinburgh-{index}",
            occurred_at=(
                now - timedelta(minutes=index + 1)
                if index < 3
                else now - timedelta(hours=1, minutes=index)
            ),
            category="news",
            lat=55.90 + (index % 10) * 0.01,
            lon=-3.25 + (index % 10) * 0.01,
            keywords=[],
            payload={},
        )
        for index in range(26)
    ]
    db_session.add_all(remote + local)
    db_session.commit()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    global_page = client.get("/events", params={"sources": "viewport-test", "limit": 5}).json()
    assert sum(row["source_event_id"].startswith("edinburgh-") for row in global_page) == 3

    query = {
        "sources": "viewport-test",
        "since": (now - timedelta(days=1)).isoformat(),
        "until": now.isoformat(),
        "west": -3.4,
        "south": 55.8,
        "east": -3.0,
        "north": 56.1,
        "positioned_only": "true",
        "limit": 7,
    }
    recovered = []
    while True:
        page = client.get("/events", params=query).json()
        recovered.extend(page)
        if len(page) < query["limit"]:
            break
        query["occurred_before"] = page[-1]["occurred_at"]
        query["occurred_before_id"] = page[-1]["id"]

    assert len(recovered) == 26
    assert {row["source_event_id"] for row in recovered} == {
        f"edinburgh-{index}" for index in range(26)
    }
    assert len({row["id"] for row in recovered}) == 26


def test_events_viewport_requires_complete_valid_bounds(db_session):
    client = _client(db_session)

    assert client.get("/events?west=-4").status_code == 422
    assert client.get("/events?west=-4&south=56&east=-3&north=55").status_code == 422
    assert client.get("/events?occurred_before_id=10").status_code == 422


def test_events_viewport_supports_antimeridian(db_session):
    now = datetime.now(UTC)
    db_session.add_all(
        [
            EventRow(
                source="dateline-test",
                source_event_id="west-side",
                occurred_at=now,
                category="news",
                lat=0,
                lon=179,
                keywords=[],
                payload={},
            ),
            EventRow(
                source="dateline-test",
                source_event_id="east-side",
                occurred_at=now,
                category="news",
                lat=0,
                lon=-179,
                keywords=[],
                payload={},
            ),
            EventRow(
                source="dateline-test",
                source_event_id="outside",
                occurred_at=now,
                category="news",
                lat=0,
                lon=0,
                keywords=[],
                payload={},
            ),
        ]
    )
    db_session.commit()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    rows = client.get(
        "/events",
        params={
            "sources": "dateline-test",
            "west": 170,
            "south": -10,
            "east": -170,
            "north": 10,
        },
    ).json()
    assert {row["source_event_id"] for row in rows} == {"west-side", "east-side"}


def test_events_viewport_recovers_secondary_verified_place(db_session):
    now = datetime.now(UTC)
    db_session.add(
        EventRow(
            source="rss-multi-place",
            source_event_id="london-and-edinburgh",
            occurred_at=now,
            category="news",
            country="GB",
            lat=51.5074,
            lon=-0.1278,
            keywords=[],
            payload={
                "place_locations": [
                    {
                        "wikidata_id": "Q84",
                        "name": "London",
                        "lat": 51.5074,
                        "lon": -0.1278,
                    },
                    {
                        "wikidata_id": "Q23436",
                        "name": "Edinburgh",
                        "lat": 55.9533,
                        "lon": -3.1883,
                    },
                ]
            },
        )
    )
    db_session.commit()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    rows = client.get(
        "/events",
        params={
            "sources": "rss-multi-place",
            "west": -3.4,
            "south": 55.8,
            "east": -3.0,
            "north": 56.1,
            "positioned_only": "true",
        },
    ).json()
    assert [row["source_event_id"] for row in rows] == ["london-and-edinburgh"]


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
                payload={"title": "A headline"},
            ),
            EventRow(
                source="gdelt",
                source_event_id="gb-1",
                occurred_at=now - timedelta(seconds=1),
                category="conflict",
                country="GB",
                keywords=[],
                payload={"title": "A headline"},
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
    # The time scrubber sizes its reach from this, so it has to be the oldest
    # row the source still holds rather than the oldest inside `days`.
    earliest = datetime.fromisoformat(by_source["rss-bbc-world"]["earliest_occurred_at"])
    # SQLite hands timestamps back without a zone, Postgres with one; the value
    # under test is the instant, not which of the two the fixture ran on.
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=UTC)
    assert abs((earliest - (now - timedelta(days=40))).total_seconds()) < 1


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
                payload={"title": "A headline"},
            ),
            EventRow(
                source="gdelt",
                source_event_id="new",
                occurred_at=now,
                category="conflict",
                keywords=[],
                payload={"title": "A headline"},
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


def _seed_stats(session):
    """Events spread across countries, sources and time for /events/stats."""
    now = datetime.now(UTC)
    rows = [
        EventRow(
            source="gdelt",
            source_event_id=f"s-us-{i}",
            occurred_at=now - timedelta(hours=i),
            category="geopolitical",
            country="US",
            keywords=[],
            payload={"title": "A headline"},
        )
        for i in range(5)
    ]
    rows += [
        EventRow(
            source="rss-bbc-world",
            source_event_id=f"s-gb-{i}",
            occurred_at=now - timedelta(hours=i),
            category="news",
            country="GB",
            keywords=[],
            payload={},
        )
        for i in range(3)
    ]
    # Non-renderable: excluded from the stats by default.
    rows += [
        EventRow(
            source="nasa-firms",
            source_event_id=f"s-fire-{i}",
            occurred_at=now - timedelta(hours=i),
            category="hazard",
            country="AU",
            keywords=[],
            payload={},
        )
        for i in range(50)
    ]
    rows.append(
        EventRow(
            source="opensky-adsb",
            source_event_id="s-air-1",
            occurred_at=now,
            category="tracking",
            country="FR",
            keywords=[],
            payload={"aircraft_count": 4000},
        )
    )
    # Outside the requested window.
    rows.append(
        EventRow(
            source="gdelt",
            source_event_id="s-old",
            occurred_at=now - timedelta(days=90),
            category="geopolitical",
            country="BR",
            keywords=[],
            payload={"title": "A headline"},
        )
    )
    session.add_all(rows)
    session.commit()


def _stats_client(db_session):
    _seed_stats(db_session)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_stats_counts_only_renderable_sources(db_session):
    client = _stats_client(db_session)
    body = client.get("/events/stats?days=30").json()
    # 5 gdelt + 3 rss; the 50 FIRMS rows and the opensky aggregate do not count.
    assert body["total"] == 8
    assert body["countries"] == 2
    assert body["sources"] == 2


def test_stats_honours_the_day_window(db_session):
    client = _stats_client(db_session)
    body = client.get("/events/stats?days=1").json()
    assert body["total"] == 8  # the 90-day-old row stays out
    wide = client.get("/events/stats?days=365").json()
    assert wide["total"] == 9
    assert wide["countries"] == 3


def test_stats_ranks_top_countries(db_session):
    client = _stats_client(db_session)
    body = client.get("/events/stats?days=30").json()
    assert body["top_countries"][0] == {"country": "US", "count": 5}
    assert body["top_countries"][1] == {"country": "GB", "count": 3}
    assert all(row["country"] not in {"AU", "FR"} for row in body["top_countries"])


def test_stats_exclude_param_overrides_the_default(db_session):
    client = _stats_client(db_session)
    body = client.get("/events/stats?days=30&exclude=gdelt").json()
    # Explicit exclude replaces the default, so FIRMS and opensky come back.
    assert body["total"] == 54
    assert {"country": "AU", "count": 50} in body["top_countries"]


def test_stats_spark_has_fixed_buckets_summing_to_total(db_session):
    client = _stats_client(db_session)
    body = client.get("/events/stats?days=30").json()
    assert len(body["spark"]) == 24
    assert sum(body["spark"]) == body["total"]


def test_stats_empty_window_is_zeroed_not_missing(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    body = client.get("/events/stats?days=30").json()
    assert body["total"] == 0
    assert body["countries"] == 0
    assert body["top_countries"] == []
    assert body["spark"] == [0] * 24
