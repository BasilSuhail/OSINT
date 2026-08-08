"""One article must not become several rows on the map (#772).

GDELT emits one `GLOBALEVENTID` per actor pairing it extracts from an
article, so a single BBC story arrives as three rows carrying the same
headline, the same coordinate and the same `source_url`. They are valid
analytical records and storage keeps every one of them. A reader looking at
a list sees the same sentence three times.

Measured on the live table before this was written: 8,670 GDELT rows over
three days carried 3,958 distinct (`source_url`, `event_root_code`) pairs,
and one article contributed forty rows.
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


NOW = datetime(2026, 8, 6, 12, 15, tzinfo=UTC)
ARTICLE = "https://www.bbc.co.uk/news/articles/c8dny8my1jpo"


def _relation(
    source_event_id: str,
    *,
    url: str = ARTICLE,
    code: str = "17",
    mentions: float = 1.0,
    minutes_ago: int = 0,
    lat: float | None = 55.95,
    lon: float | None = -3.2,
    title: str = "Police make 49 arrests in Edinburgh city centre crackdown",
) -> EventRow:
    return EventRow(
        source="gdelt",
        source_event_id=source_event_id,
        occurred_at=NOW - timedelta(minutes=minutes_ago),
        category="geopolitical",
        keywords=[],
        lat=lat,
        lon=lon,
        payload={
            "title": title,
            "source_url": url,
            "event_root_code": code,
            "num_mentions": mentions,
        },
    )


def _client(session) -> TestClient:
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def _ids(rows: list[dict]) -> set[str]:
    return {row["source_event_id"] for row in rows}


def test_one_article_is_one_row(db_session):
    """Three relations, one article, one row on the map."""
    db_session.add_all(
        [
            _relation("1317084073", mentions=10.0),
            _relation("1317084269", mentions=6.0),
            _relation("1317084270", mentions=4.0),
        ]
    )
    db_session.commit()

    rows = _client(db_session).get("/events").json()
    assert len(rows) == 1
    # The most-cited relation survives: it is the one carrying the most
    # evidence that the article was read anywhere.
    assert rows[0]["source_event_id"] == "1317084073"


def test_the_survivor_says_how_many_relations_it_stands_for(db_session):
    """A collapse a reader cannot see is a collapse nobody can audit."""
    db_session.add_all([_relation("a", mentions=2.0), _relation("b", mentions=1.0)])
    db_session.commit()

    rows = _client(db_session).get("/events").json()
    assert rows[0]["relation_count"] == 2


def test_uncollapsed_rows_report_one_relation(db_session):
    db_session.add_all([_relation("solo")])
    db_session.commit()

    rows = _client(db_session).get("/events").json()
    assert rows[0]["relation_count"] == 1


def test_one_article_in_two_places_stays_two_rows(db_session):
    """An article about strikes in two cities is two things that happened.

    Over three days of live rows, 1,049 of the 1,860 articles producing more
    than one row placed them at different coordinates, so a URL-only key would
    have erased a real place from the map in most multi-row cases.
    """
    db_session.add_all(
        [
            _relation("edinburgh", lat=55.95, lon=-3.2),
            _relation("glasgow", lat=55.86, lon=-4.25),
        ]
    )
    db_session.commit()

    rows = _client(db_session).get("/events").json()
    assert _ids(rows) == {"edinburgh", "glasgow"}


def test_event_codes_do_not_keep_one_point_saying_the_same_thing_twice(db_session):
    """GDELT classified one sentence as both `Coerce` and `Fight`; 180 articles
    did this at a single coordinate in the measured window. The reader sees one
    headline pinned to one street and does not care which codes it earned."""
    db_session.add_all(
        [
            _relation("coerce", code="17", mentions=2.0),
            _relation("fight", code="19", mentions=1.0),
        ]
    )
    db_session.commit()

    rows = _client(db_session).get("/events").json()
    assert _ids(rows) == {"coerce"}
    assert rows[0]["relation_count"] == 2


def test_relations_from_different_articles_both_survive(db_session):
    db_session.add_all(
        [
            _relation("bbc", url=ARTICLE),
            _relation("stv", url="https://news.stv.tv/east-central/edinburgh-arrests"),
        ]
    )
    db_session.commit()

    rows = _client(db_session).get("/events").json()
    assert _ids(rows) == {"bbc", "stv"}


def test_non_gdelt_rows_are_never_collapsed(db_session):
    """RSS duplicates are a different defect with a different fix (#751), and
    a sensor reading that repeats is a reading, not a duplicate."""
    db_session.add_all(
        [
            EventRow(
                source="rss-bbc-uk",
                source_event_id=f"rss-{n}",
                occurred_at=NOW,
                category="geopolitical",
                keywords=[],
                payload={"title": "Same headline", "source_url": ARTICLE},
            )
            for n in range(3)
        ]
    )
    db_session.commit()

    rows = _client(db_session).get("/events").json()
    assert len(rows) == 3


def test_gdelt_rows_without_an_article_url_are_left_alone(db_session):
    """No URL is no evidence of shared provenance. Collapsing those would
    merge unrelated events that happen to sit at one city centroid."""
    db_session.add_all(
        [
            EventRow(
                source="gdelt",
                source_event_id=f"nourl-{n}",
                occurred_at=NOW,
                category="geopolitical",
                keywords=[],
                lat=55.95,
                lon=-3.2,
                # A headline, because #810 filters rows a reader cannot read
                # and this test is about provenance, not about titles.
                payload={"event_root_code": "17", "title": f"Story {n}"},
            )
            for n in range(3)
        ]
    )
    db_session.commit()

    rows = _client(db_session).get("/events").json()
    assert len(rows) == 3


def test_coordless_relations_from_one_article_still_collapse(db_session):
    """A row with no position never reaches the map, but it does reach every
    list, which is where the repetition was reported."""
    db_session.add_all(
        [
            _relation("a", lat=None, lon=None, mentions=2.0),
            _relation("b", lat=None, lon=None, mentions=1.0),
        ]
    )
    db_session.commit()

    rows = _client(db_session).get("/events").json()
    assert _ids(rows) == {"a"}


def test_limit_counts_rows_a_reader_sees(db_session):
    """The limit applies after the collapse, not before it.

    `fetchAllEventPages` stops paging as soon as a page is shorter than the
    page size, so a page thinned after the SQL limit would end the map early
    — the truncation #770 was about.
    """
    db_session.add_all(
        [
            _relation("dup-1", mentions=3.0),
            _relation("dup-2", mentions=2.0),
            _relation("dup-3", mentions=1.0),
            _relation("other-1", url="https://example.com/a", minutes_ago=1),
            _relation("other-2", url="https://example.com/b", minutes_ago=2),
        ]
    )
    db_session.commit()

    rows = _client(db_session).get("/events?limit=3").json()
    assert len(rows) == 3
    assert _ids(rows) == {"dup-1", "other-1", "other-2"}


def test_collapse_can_be_turned_off_for_analysis(db_session):
    """Counting how often an article was cited is a question about relations.
    The escape hatch keeps that answerable without reading the table directly."""
    db_session.add_all([_relation("a", mentions=2.0), _relation("b", mentions=1.0)])
    db_session.commit()

    rows = _client(db_session).get("/events?collapse=false").json()
    assert _ids(rows) == {"a", "b"}


def test_collapse_survives_the_bounding_box_filter(db_session):
    """The viewport query takes a different branch through the endpoint, and
    the map is where the duplicates were seen."""
    db_session.add_all([_relation("a", mentions=2.0), _relation("b", mentions=1.0)])
    db_session.commit()

    rows = _client(db_session).get("/events?west=-3.8&south=55.6&east=-2.7&north=56.2").json()
    assert _ids(rows) == {"a"}
