"""ACLED conflict/event API fetcher.

Credential-gated: without ``ACLED_EMAIL`` + ``ACLED_API_KEY`` this fetcher is a
no-op. That keeps local/dev runs licence-safe while allowing deployments with
approved ACLED access to ingest recent conflict/protest events.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx

from app.enrichment.country import country_for
from app.enrichment.country_codes import iso3_to_iso2
from app.models import Category, Event
from app.settings import settings
from app.sources.base import Fetcher

ACLED_API_URL: Final[str] = "https://api.acleddata.com/acled/read"
ACLED_USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"

_EVENT_TYPE_SEVERITY: Final[dict[str, float]] = {
    "battles": 0.9,
    "explosions/remote violence": 0.85,
    "violence against civilians": 0.8,
    "riots": 0.65,
    "protests": 0.45,
    "strategic developments": 0.35,
}


def _parse_float(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_int(raw: Any) -> int | None:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _parse_date(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _severity(record: dict[str, Any]) -> float:
    fatalities = _parse_int(record.get("fatalities")) or 0
    event_type = str(record.get("event_type") or "").strip().lower()
    base = _EVENT_TYPE_SEVERITY.get(event_type, 0.5)
    fatality_bump = min(0.2, fatalities / 50.0)
    return max(0.0, min(1.0, base + fatality_bump))


def record_to_event(record: dict[str, Any], *, fetched_at: datetime) -> Event | None:
    """Convert one ACLED API record to a canonical Event."""
    event_id = str(record.get("event_id_cnty") or record.get("event_id_no_cnty") or "").strip()
    if not event_id:
        return None
    occurred_at = _parse_date(record.get("event_date"))
    if occurred_at is None:
        return None

    lat = _parse_float(record.get("latitude"))
    lon = _parse_float(record.get("longitude"))
    country = iso3_to_iso2(str(record.get("iso3") or "").strip() or None)
    if country is None and lat is not None and lon is not None:
        country = country_for(lat, lon)

    event_type = str(record.get("event_type") or "").strip() or None
    sub_event_type = str(record.get("sub_event_type") or "").strip() or None
    actor1 = str(record.get("actor1") or "").strip() or None
    actor2 = str(record.get("actor2") or "").strip() or None
    fatalities = _parse_int(record.get("fatalities"))
    location = str(record.get("location") or "").strip() or None

    payload = {
        "event_id_cnty": record.get("event_id_cnty"),
        "event_id_no_cnty": record.get("event_id_no_cnty"),
        "event_date": record.get("event_date"),
        "year": record.get("year"),
        "event_type": event_type,
        "sub_event_type": sub_event_type,
        "actor1": actor1,
        "actor2": actor2,
        "fatalities": fatalities,
        "location": location,
        "admin1": record.get("admin1"),
        "admin2": record.get("admin2"),
        "admin3": record.get("admin3"),
        "source": record.get("source"),
        "source_scale": record.get("source_scale"),
        "notes": record.get("notes"),
        "iso3": record.get("iso3"),
    }

    keywords = ["acled", "conflict"]
    if event_type:
        keywords.append(event_type.lower())
    if sub_event_type:
        keywords.append(sub_event_type.lower())

    return Event(
        source="acled",
        source_event_id=event_id,
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.GEOPOLITICAL,
        severity=_severity(record),
        confidence=None,
        keywords=keywords,
        country=country,
        lat=lat,
        lon=lon,
        payload=payload,
    )


def parse_acled_response(body: dict[str, Any], *, fetched_at: datetime) -> list[Event]:
    records = body.get("data") or []
    if not isinstance(records, list):
        return []
    events: list[Event] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        event = record_to_event(record, fetched_at=fetched_at)
        if event is not None:
            events.append(event)
    return events


class AcledFetcher(Fetcher):
    name = "acled"
    queue = "slow"

    def __init__(self, *, lookback_days: int = 7, limit: int = 500, timeout_seconds: float = 30.0):
        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.lookback_days = lookback_days
        self.limit = limit
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> list[Event]:
        if not settings.acled_email or not settings.acled_api_key:
            return []
        fetched_at = datetime.now(UTC)
        event_date = (fetched_at - timedelta(days=self.lookback_days)).date().isoformat()
        params = {
            "email": settings.acled_email,
            "key": settings.acled_api_key,
            "event_date": event_date,
            "event_date_where": ">=",
            "limit": str(self.limit),
            "format": "json",
        }
        with httpx.Client(
            timeout=self.timeout_seconds,
            headers={"User-Agent": ACLED_USER_AGENT, "Accept": "application/json"},
        ) as client:
            response = client.get(ACLED_API_URL, params=params)
            response.raise_for_status()
            return parse_acled_response(response.json(), fetched_at=fetched_at)

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return f"/mnt/data/parquet/acled/year={now.year}/month={now.month:02d}/day={now.day:02d}/"
