"""UK Police: survive the rate limit, and survive retention (#765).

Two defects, both measured on the live system.

**The rate limit.** The fetcher asks `data.police.uk` once per city in a tight
loop with no pacing and no retry. A 429 propagates, the source is quarantined,
and the panel of cities after the failing one is never asked at all.

**Retention deletes everything it fetches.** The API publishes about two
months in arrears — it offered `2026-06-01` on 2026-08-08 — and every row is
pinned to the first of that month, so a row is 68 days old the moment it
arrives. `uk-police` retention is 30 days keyed on `occurred_at`, so
housekeeping deleted each batch on its next pass:

```
ingest_health   4 successful days of the last 6
events table    0 rows
```

The source was healthy and contributed nothing. Fixing the 429 alone would
have produced a green light over an empty layer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import housekeeping
from app.db_models import Base, EventRow
from app.sources.uk_police_fetcher import UKCity, UKPoliceFetcher

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
CITIES = (UKCity(name="Manchester", lat=53.4808, lon=-2.2426),)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        yield s


def _crime(month: str = "2026-06") -> dict:
    return {
        "category": "violent-crime",
        "month": month,
        "id": 101,
        "location": {
            "latitude": "53.4808",
            "longitude": "-2.2426",
            "street": {"name": "On or near"},
        },
    }


class _Transport(httpx.MockTransport):
    """Answers the last-updated probe, then plays a scripted response list."""

    def __init__(self, responses: list[httpx.Response], *, month: str = "2026-06-01") -> None:
        self.requests: list[str] = []
        queue = list(responses)

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(str(request.url))
            if "crime-last-updated" in str(request.url):
                return httpx.Response(200, json={"date": month})
            return queue.pop(0)

        super().__init__(handler)


def _fetcher(transport: _Transport, sleeps: list[float]) -> UKPoliceFetcher:
    fetcher = UKPoliceFetcher(cities=CITIES)
    fetcher._transport = transport  # type: ignore[attr-defined]
    fetcher._sleep = sleeps.append  # type: ignore[attr-defined]
    return fetcher


class TestRateLimit:
    def test_a_429_is_retried_rather_than_raised(self) -> None:
        sleeps: list[float] = []
        transport = _Transport([httpx.Response(429), httpx.Response(200, json=[_crime()])])
        events = _fetcher(transport, sleeps).fetch()
        assert len(events) == 1, "the retry never happened"
        assert sleeps, "it retried without waiting"

    def test_the_hosts_retry_after_is_honoured(self) -> None:
        sleeps: list[float] = []
        transport = _Transport(
            [
                httpx.Response(429, headers={"retry-after": "7"}),
                httpx.Response(200, json=[_crime()]),
            ]
        )
        _fetcher(transport, sleeps).fetch()
        assert sleeps[0] == 7.0

    def test_it_gives_up_and_raises_so_the_quarantine_can_rest_it(self) -> None:
        """A feed that answers 429 to every attempt should be rested by the
        quarantine, not hammered by a fetcher that retries forever."""
        sleeps: list[float] = []
        transport = _Transport([httpx.Response(429) for _ in range(6)])
        with pytest.raises(httpx.HTTPStatusError):
            _fetcher(transport, sleeps).fetch()
        assert len(sleeps) <= 4, "backing off should be bounded"

    def test_cities_are_paced_rather_than_fired_in_a_burst(self) -> None:
        sleeps: list[float] = []
        cities = (
            UKCity(name="Manchester", lat=53.4808, lon=-2.2426),
            UKCity(name="Leeds", lat=53.8008, lon=-1.5491),
            UKCity(name="Bristol", lat=51.4545, lon=-2.5879),
        )
        transport = _Transport([httpx.Response(200, json=[_crime()]) for _ in cities])
        fetcher = UKPoliceFetcher(cities=cities)
        fetcher._transport = transport  # type: ignore[attr-defined]
        fetcher._sleep = sleeps.append  # type: ignore[attr-defined]
        fetcher.fetch()
        assert len(sleeps) >= len(cities) - 1, "the panel was fired as a burst"


class TestRetentionMatchesPublicationLag:
    def _row(self, *, occurred_days_ago: int, fetched_days_ago: int) -> EventRow:
        return EventRow(
            source="uk-police",
            source_event_id=f"crime-{occurred_days_ago}-{fetched_days_ago}",
            occurred_at=NOW - timedelta(days=occurred_days_ago),
            fetched_at=NOW - timedelta(days=fetched_days_ago),
            category="news",
            keywords=[],
            payload={"month": "2026-06"},
        )

    def test_a_row_that_arrived_today_survives_the_prune(self, session) -> None:
        """The defect: published 68 days ago, fetched an hour ago, deleted the
        same day by a window keyed on the publication date."""
        session.add(self._row(occurred_days_ago=68, fetched_days_ago=0))
        session.commit()
        housekeeping.prune_events(session, now=NOW)
        assert session.execute(select(EventRow)).scalars().all(), "today's fetch was deleted"

    def test_a_row_ingested_long_ago_is_still_pruned(self, session) -> None:
        session.add(self._row(occurred_days_ago=200, fetched_days_ago=45))
        session.commit()
        housekeeping.prune_events(session, now=NOW)
        assert session.execute(select(EventRow)).scalars().all() == []

    def test_other_sources_still_prune_on_when_the_event_happened(self, session) -> None:
        """A news story fetched today but dated six months ago is old news,
        and #571's boundary rule depends on that staying true."""
        session.add(
            EventRow(
                source="rss-bbc-uk",
                source_event_id="old-news",
                occurred_at=NOW - timedelta(days=180),
                fetched_at=NOW,
                category="geopolitical",
                keywords=[],
                payload={"title": "old"},
            )
        )
        session.commit()
        housekeeping.prune_events(session, now=NOW)
        assert session.execute(select(EventRow)).scalars().all() == []
