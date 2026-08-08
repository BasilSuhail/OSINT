"""Module L3 — UK Police street-crime fetcher (data.police.uk).

Pulls the latest published month of street-crime incidents around a fixed
panel of UK city centres so the dashboard map carries real city-level
incident data alongside the national / international news layer.

Important coverage note:

- ``data.police.uk`` covers England + Wales only.
- Police Scotland and the PSNI (Northern Ireland) publish elsewhere and are
  not exposed via this API.
- So Edinburgh / Glasgow / Belfast won't surface here. The PR description
  records this explicitly so it does not surprise anyone later.

Each crime emits one Event with ``source='uk-police'`` and
``category=NEWS``. Severity is a simple per-category lookup; high-harm
categories (violent crime, robbery) sit at 0.8 while quality-of-life
categories (anti-social behaviour) sit at 0.3. Source URL points back to
the data.police.uk record.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from app.models import Category, Event
from app.sources.base import Fetcher

DATA_POLICE_BASE: Final[str] = "https://data.police.uk/api"
UK_POLICE_USER_AGENT: Final[str] = "OSINT-project/0.0.1 (academic)"

#: Gap between city requests. The panel used to be fired as a burst, which is
#: what earns a 429 from an open public API asking for nothing but politeness
#: (#765).
CITY_SPACING_SECONDS: Final[float] = 1.0

#: Attempts per city before the failure is allowed to propagate. Bounded on
#: purpose: past this the quarantine should rest the source rather than the
#: fetcher retrying on its own forever.
MAX_ATTEMPTS: Final[int] = 3

#: Wait after a 429 that carries no `Retry-After`, multiplied by the attempt.
BACKOFF_SECONDS: Final[float] = 5.0

#: Severity table per upstream category. Values tuned so violent / weapons
#: events dominate the colour scale while bicycle theft / public order
#: sit mid-band. Anything missing from the table defaults to 0.4.
CRIME_SEVERITY: Final[dict[str, float]] = {
    "violent-crime": 0.85,
    "robbery": 0.80,
    "weapons": 0.85,
    "possession-of-weapons": 0.80,
    "burglary": 0.65,
    "vehicle-crime": 0.55,
    "theft-from-the-person": 0.55,
    "shoplifting": 0.40,
    "criminal-damage-arson": 0.55,
    "bicycle-theft": 0.35,
    "other-theft": 0.40,
    "drugs": 0.50,
    "public-order": 0.40,
    "anti-social-behaviour": 0.30,
    "other-crime": 0.40,
}


@dataclass(frozen=True)
class UKCity:
    """City-centre coordinate the fetcher will hit. England + Wales only."""

    name: str
    lat: float
    lon: float


#: Default panel. data.police.uk returns crimes within ~1 mile of each point;
#: covering ~6 city centres gives the map a representative spread without
#: blowing the rate budget. Edinburgh / Glasgow / Belfast intentionally
#: absent — see module docstring.
DEFAULT_PANEL: Final[tuple[UKCity, ...]] = (
    UKCity("London", 51.5074, -0.1278),
    UKCity("Manchester", 53.4808, -2.2426),
    UKCity("Birmingham", 52.4862, -1.8904),
    UKCity("Liverpool", 53.4084, -2.9916),
    UKCity("Leeds", 53.8008, -1.5491),
    UKCity("Bristol", 51.4545, -2.5879),
)


def _severity_for(category: str | None) -> float:
    if not category:
        return 0.4
    return CRIME_SEVERITY.get(category.strip().lower(), 0.4)


def _parse_lat_lon(location: dict[str, Any]) -> tuple[float, float] | None:
    try:
        lat = float(location["latitude"])
        lon = float(location["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    return lat, lon


def crime_to_event(record: dict[str, Any], *, city: UKCity, fetched_at: datetime) -> Event | None:
    """Pure transformation: one data.police.uk crime record → canonical Event."""
    if not isinstance(record, dict):
        return None
    rec_id = record.get("id")
    if rec_id in (None, ""):
        return None
    category = (record.get("category") or "").strip().lower() or None

    location = record.get("location")
    coords = _parse_lat_lon(location) if isinstance(location, dict) else None
    if coords is None:
        return None
    lat, lon = coords

    month = (record.get("month") or "").strip()
    try:
        # API publishes month as 'YYYY-MM'. Pin to first of month UTC.
        occurred_at = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
    except ValueError:
        occurred_at = fetched_at

    street = location.get("street") if isinstance(location, dict) else None
    street_name = street.get("name") if isinstance(street, dict) and street.get("name") else None

    payload: dict[str, Any] = {
        "title": f"{category.replace('-', ' ').title()}" if category else "Crime",
        "category_raw": category,
        "month": month or None,
        "city": city.name,
        "street": street_name,
        "outcome": (record.get("outcome_status") or {}).get("category"),
        "context": (record.get("context") or "").strip() or None,
        "source_url": (f"https://data.police.uk/data/policing-crime/?type=table&crime={rec_id}"),
        "persistent_id": (record.get("persistent_id") or "").strip() or None,
    }

    keywords = ["uk-police", "crime", category or "uncategorised", city.name.lower()]

    return Event(
        source="uk-police",
        source_event_id=str(rec_id),
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.NEWS,
        severity=_severity_for(category),
        confidence=None,
        keywords=keywords,
        country="GB",
        lat=lat,
        lon=lon,
        payload=payload,
    )


def parse_crime_list(
    records: list[dict[str, Any]], *, city: UKCity, fetched_at: datetime
) -> list[Event]:
    """Pure: parse a city's worth of crime records into Events."""
    if not isinstance(records, list):
        return []
    out: list[Event] = []
    for rec in records:
        ev = crime_to_event(rec, city=city, fetched_at=fetched_at)
        if ev is not None:
            out.append(ev)
    return out


class UKPoliceFetcher(Fetcher):
    """Pulls the latest published month of street crimes around each city."""

    name = "uk-police"
    queue = "slow"

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        cities: tuple[UKCity, ...] = DEFAULT_PANEL,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not cities:
            raise ValueError("at least one city required")
        self.timeout_seconds = timeout_seconds
        self.cities = cities
        #: Injected by the tests so pacing and backoff can be exercised without
        #: spending the wall-clock time they are measured in.
        self._sleep = time.sleep
        self._transport: httpx.BaseTransport | None = None

    def _latest_date(self, client: httpx.Client) -> str | None:
        """data.police.uk publishes about 2 months in arrears; ask the API."""
        try:
            response = client.get(f"{DATA_POLICE_BASE}/crime-last-updated")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        full_date = payload.get("date")
        if not isinstance(full_date, str) or len(full_date) < 7:
            return None
        # Returned shape is "YYYY-MM-DD" but the crimes endpoint wants "YYYY-MM".
        return full_date[:7]

    def _get_with_backoff(self, client: httpx.Client, url: str, params: dict) -> httpx.Response:
        """One city, retried on 429 within a bounded budget (#765).

        The host publishes no rate limit and asks for restraint, so restraint
        is what this does: honour `Retry-After` when it is sent, back off on a
        rising schedule when it is not, and let the failure through once the
        budget is spent so the quarantine can rest the source properly.
        """
        for attempt in range(1, MAX_ATTEMPTS + 1):
            response = client.get(url, params=params)
            if response.status_code != 429 or attempt == MAX_ATTEMPTS:
                response.raise_for_status()
                return response
            self._sleep(_retry_after(response) or BACKOFF_SECONDS * attempt)
        raise AssertionError("unreachable")  # pragma: no cover

    def fetch(self) -> list[Event]:
        fetched_at = datetime.now(UTC)
        events: list[Event] = []
        with httpx.Client(
            timeout=self.timeout_seconds,
            headers={"User-Agent": UK_POLICE_USER_AGENT},
            transport=self._transport,
        ) as client:
            month = self._latest_date(client) or fetched_at.strftime("%Y-%m")
            for index, city in enumerate(self.cities):
                if index:
                    self._sleep(CITY_SPACING_SECONDS)
                response = self._get_with_backoff(
                    client,
                    f"{DATA_POLICE_BASE}/crimes-street/all-crime",
                    {"lat": city.lat, "lng": city.lon, "date": month},
                )
                try:
                    records = response.json()
                except ValueError:
                    continue
                if not isinstance(records, list):
                    continue
                events.extend(parse_crime_list(records, city=city, fetched_at=fetched_at))
        return events

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return (
            f"/mnt/data/parquet/uk-police/year={now.year}/month={now.month:02d}/day={now.day:02d}/"
        )


def _retry_after(response: httpx.Response) -> float | None:
    """The host's own `Retry-After`, when it sends a usable one."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:  # HTTP-date form; the schedule covers it
        return None
