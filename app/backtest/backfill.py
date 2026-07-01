"""Historical backfill for registry events."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from httpx import Client, ConnectError, HTTPError, ReadTimeout

from app.backtest.registry import RegistryEvent
from app.models import Event
from app.persistence import upsert_events
from app.sources.gdelt_parser import parse_csv_body
from app.sources.usgs_quake_fetcher import parse_geojson_body


class BackfillSource(Protocol):
    """Backfill source interface: fetch events for a country/date window."""

    name: str

    def fetch_range(self, country: str, start: date, end: date) -> list[Event]: ...


class UsgsBackfill:
    """USGS historical adapter for backfill windows."""

    name = "usgs-quake"

    def __init__(self, client: Client | None = None, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.client = client
        self.timeout_seconds = timeout_seconds

    def fetch_range(self, country: str, start: date, end: date) -> list[Event]:
        params = {
            "format": "geojson",
            "starttime": start.isoformat(),
            "endtime": end.isoformat(),
            "minmagnitude": "2.5",
        }
        with _http_client(self.client, self.timeout_seconds) as client:
            try:
                response = client.get(
                    "https://earthquake.usgs.gov/fdsnws/event/1/query",
                    params=params,
                )
                response.raise_for_status()
            except (ConnectError, HTTPError, ReadTimeout, OSError):
                return []
        country_upper = country.upper()
        return [
            event
            for event in parse_geojson_body(response.text, fetched_at=datetime.now(UTC))
            if (event.country == country_upper)
        ]


class GdeltBackfill:
    """GDELT historical adapter for backfill windows."""

    name = "gdelt"

    def __init__(self, client: Client | None = None, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.client = client
        self.timeout_seconds = timeout_seconds

    def fetch_range(self, country: str, start: date, end: date) -> list[Event]:
        params = {
            "query": f"country:{country.upper()}",
            "mode": "artlist",
            "format": "tsv",
            "maxrecords": 250,
            "startdatetime": _format_gdelt_datetime(start),
            "enddatetime": _format_gdelt_datetime(end, is_end=True),
        }
        with _http_client(self.client, self.timeout_seconds) as client:
            try:
                response = client.get(
                    "https://api.gdeltproject.org/api/v2/doc/doc",
                    params=params,
                )
                response.raise_for_status()
            except (ConnectError, HTTPError, ReadTimeout, OSError):
                return []
        return parse_csv_body(response.text, fetched_at=datetime.now(UTC))


def _format_gdelt_datetime(day: date, *, is_end: bool = False) -> str:
    """Format a date as GDELT doc API datetime expected by the 2.0 export API."""
    suffix = "235959" if is_end else "000000"
    return f"{day:%Y%m%d}{suffix}"


@contextmanager
def _http_client(
    client: Client | None,
    timeout_seconds: float,
) -> Iterator[Client]:
    if client is not None:
        yield client
    else:
        with Client(timeout=timeout_seconds) as managed:
            yield managed


def backfill_event(
    session,
    event: RegistryEvent,
    sources: list[BackfillSource],
    *,
    lookback_days: int = 45,
    lookahead_days: int = 15,
) -> int:
    """Fetch + upsert the historical window for one registry event."""
    if lookback_days < 0 or lookahead_days < 0:
        raise ValueError("lookback_days/lookahead_days must be non-negative")

    start = event.date - timedelta(days=lookback_days)
    end = event.date + timedelta(days=lookahead_days)
    inserted = 0
    for src in sources:
        events = src.fetch_range(event.country, start, end)
        inserted += upsert_events(events, session)
    return inserted
