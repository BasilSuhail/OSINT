"""A marker with no headline is not an event (#810).

GDELT rows arrive before their headline does, and 8,457 of them in the last
seven days will never get one: `app.enrichment.gdelt_titles.pending_ids`
selects only `geo_precision == 'city'`, while every country- and
admin-precision row carries a coordinate anyway. They are drawn on invented
points — 320 sat on the geographic centre of the United States — and the
frontend renders them as `title ?? ev.source`, so the reader is shown a list
row saying "gdelt".

Storage keeps them. Analysis can still ask for them. They are not events a
reader can be shown.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import app, get_session
from app.db_models import EventRow


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


def _gdelt(
    source_event_id: str,
    *,
    title: str | None,
    lat: float | None = 55.95,
    lon: float | None = -3.2,
    minutes_ago: int = 0,
    precision: str = "city",
) -> EventRow:
    payload: dict = {
        "geo_precision": precision,
        "source_url": f"https://example.com/{source_event_id}",
    }
    if title is not None:
        payload["title"] = title
    return EventRow(
        source="gdelt",
        source_event_id=source_event_id,
        occurred_at=NOW - timedelta(minutes=minutes_ago),
        category="geopolitical",
        keywords=[],
        lat=lat,
        lon=lon,
        payload=payload,
    )


def _client(session) -> TestClient:
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def _ids(rows: list[dict]) -> set[str]:
    return {row["source_event_id"] for row in rows}


def test_a_row_with_no_headline_is_not_returned(db_session):
    db_session.add_all(
        [
            _gdelt("titled", title="Police make 49 arrests in Edinburgh"),
            _gdelt("mute", title=None, minutes_ago=1),
        ]
    )
    db_session.commit()

    assert _ids(_client(db_session).get("/events").json()) == {"titled"}


def test_an_empty_headline_counts_as_no_headline(db_session):
    """A blank string renders as blank, which is the same defect with a
    different storage shape."""
    row = _gdelt("blank", title="")
    db_session.add_all([row, _gdelt("titled", title="Something happened", minutes_ago=1)])
    db_session.commit()

    assert _ids(_client(db_session).get("/events").json()) == {"titled"}


def test_the_country_centroid_pile_disappears(db_session):
    """320 rows sat on 39.828, -98.580 — the geographic centre of the United
    States — every one of them untitled by design."""
    db_session.add_all(
        [
            _gdelt(f"centroid-{n}", title=None, lat=39.8282, lon=-98.5795, precision="country")
            for n in range(5)
        ]
    )
    db_session.commit()

    assert _client(db_session).get("/events").json() == []


def test_analysis_can_still_ask_for_them(db_session):
    """The rows are in storage and every job reading the table sees them. The
    escape hatch keeps them reachable over HTTP too, as `collapse=false` does
    for #772."""
    db_session.add_all([_gdelt("mute", title=None)])
    db_session.commit()

    rows = _client(db_session).get("/events?readable_only=false").json()
    assert _ids(rows) == {"mute"}


def test_other_sources_are_never_judged_on_a_headline(db_session):
    """A quake, an aircraft and a fire have no headline and are not supposed
    to. Their claim is the reading itself."""
    db_session.add_all(
        [
            EventRow(
                source=source,
                source_event_id=f"{source}-1",
                occurred_at=NOW,
                category="hazard",
                keywords=[],
                lat=1.0,
                lon=1.0,
                payload={"magnitude": 5.1},
            )
            for source in ("usgs-quake", "opensky-adsb", "nasa-firms")
        ]
    )
    db_session.commit()

    assert len(_client(db_session).get("/events").json()) == 3


def test_rss_rows_are_not_filtered_here(db_session):
    """An RSS row without a title cannot exist — the fetcher drops the entry —
    and if one ever did, it is a different defect with a different fix."""
    db_session.add_all(
        [
            EventRow(
                source="rss-bbc-uk",
                source_event_id="rss-1",
                occurred_at=NOW,
                category="geopolitical",
                keywords=[],
                lat=55.95,
                lon=-3.2,
                payload={"summary": "no title key at all"},
            )
        ]
    )
    db_session.commit()

    assert len(_client(db_session).get("/events").json()) == 1


def test_the_limit_counts_rows_a_reader_sees(db_session):
    """As with #772: filtering after the SQL limit returns a short page, and
    `fetchAllEventPages` reads a short page as the end of the data."""
    db_session.add_all(
        [_gdelt(f"mute-{n}", title=None, minutes_ago=n) for n in range(5)]
        + [_gdelt(f"titled-{n}", title=f"Story {n}", minutes_ago=10 + n) for n in range(3)]
    )
    db_session.commit()

    rows = _client(db_session).get("/events?limit=3").json()
    assert len(rows) == 3
    assert _ids(rows) == {"titled-0", "titled-1", "titled-2"}


def test_the_bounding_box_branch_filters_too(db_session):
    db_session.add_all(
        [_gdelt("mute", title=None), _gdelt("titled", title="Real story", minutes_ago=1)]
    )
    db_session.commit()

    rows = _client(db_session).get("/events?west=-3.8&south=55.6&east=-2.7&north=56.2").json()
    assert _ids(rows) == {"titled"}
