"""Module C — Hazards: NASA FIRMS active-fire CSV via the area API.

Pulls VIIRS_SNPP_NRT global daily active-fire hotspots via the FIRMS area API.
The API requires a free MAP_KEY (`FIRMS_MAP_KEY`); when unset, fetch() is a
no-op so local dev does not surface upstream-credential errors.

VIIRS_SNPP_NRT confidence is a text value (low / nominal / high). MODIS feeds
publish numeric 0..100 confidence; both shapes are accepted here so the fetcher
can switch upstream products without code changes.
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime, timedelta, timezone
from typing import Any, Final

import httpx

from app.models import Category, Event
from app.settings import settings
from app.sources.base import Fetcher

FIRMS_URL_TEMPLATE: Final[str] = (
    "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/"
    "VIIRS_SNPP_NRT/world/1/{date}"
)
FIRMS_USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"

_TEXT_CONFIDENCE_SEVERITY: Final[dict[str, float]] = {
    "low": 0.2,
    "nominal": 0.5,
    "high": 0.9,
}


def _confidence_to_severity(raw: str | None) -> float | None:
    if raw is None:
        return None
    cleaned = raw.strip().lower()
    if not cleaned:
        return None
    if cleaned in _TEXT_CONFIDENCE_SEVERITY:
        return _TEXT_CONFIDENCE_SEVERITY[cleaned]
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return max(0.0, min(value / 100.0, 1.0))


def hash_event_id(
    lat: str, lon: str, acq_date: str, acq_time: str, satellite: str
) -> str:
    payload = f"{lat}|{lon}|{acq_date}|{acq_time}|{satellite}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_acq_time(acq_date: str, acq_time: str) -> datetime | None:
    """Combine FIRMS acq_date (YYYY-MM-DD) and acq_time (HHMM) into UTC datetime."""
    try:
        time_str = acq_time.zfill(4)
        hour = int(time_str[:2])
        minute = int(time_str[2:])
        date = datetime.strptime(acq_date, "%Y-%m-%d")
        return date.replace(hour=hour, minute=minute, tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def row_to_event(row: dict[str, str], *, fetched_at: datetime) -> Event | None:
    """Convert a FIRMS CSV row (already parsed into a dict) to an Event."""
    lat_raw = row.get("latitude", "")
    lon_raw = row.get("longitude", "")
    acq_date = row.get("acq_date", "")
    acq_time = row.get("acq_time", "")
    satellite = row.get("satellite", "")
    confidence_raw = row.get("confidence")

    if not lat_raw or not lon_raw or not acq_date or not acq_time:
        return None

    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except ValueError:
        return None

    occurred_at = _parse_acq_time(acq_date, acq_time)
    if occurred_at is None:
        return None

    severity = _confidence_to_severity(confidence_raw)

    source_event_id = hash_event_id(lat_raw, lon_raw, acq_date, acq_time, satellite)

    payload: dict[str, Any] = {
        "acq_date": acq_date,
        "acq_time": acq_time,
        "satellite": satellite,
        "instrument": row.get("instrument"),
        "confidence_raw": confidence_raw,
        "brightness": row.get("brightness"),
        "bright_t31": row.get("bright_t31"),
        "frp": row.get("frp"),
        "daynight": row.get("daynight"),
    }

    return Event(
        source="nasa-firms",
        source_event_id=source_event_id,
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.HAZARD,
        severity=severity,
        confidence=None,
        keywords=["firms", "fire"],
        country=None,
        lat=lat,
        lon=lon,
        payload=payload,
    )


def parse_csv_body(body: str, *, fetched_at: datetime) -> list[Event]:
    """Parse the FIRMS CSV body into Events. Never raises on malformed rows."""
    if not body.strip():
        return []
    reader = csv.DictReader(io.StringIO(body))
    events: list[Event] = []
    for row in reader:
        event = row_to_event(row, fetched_at=fetched_at)
        if event is not None:
            events.append(event)
    return events


class NasaFirmsFetcher(Fetcher):
    """NASA FIRMS active-fire fetcher."""

    name = "nasa-firms"
    queue = "slow"

    def __init__(self, *, timeout_seconds: float = 60.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def _target_date(self) -> str:
        # FIRMS publishes near-real-time data. Use the prior UTC day so the
        # CSV is reliably populated when we poll.
        return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    def fetch(self) -> list[Event]:
        if not settings.firms_map_key:
            return []
        fetched_at = datetime.now(timezone.utc)
        url = FIRMS_URL_TEMPLATE.format(
            map_key=settings.firms_map_key, date=self._target_date()
        )
        with httpx.Client(
            timeout=self.timeout_seconds, headers={"User-Agent": FIRMS_USER_AGENT}
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            return parse_csv_body(response.text, fetched_at=fetched_at)

    def archive_path(self) -> str:
        now = datetime.now(timezone.utc)
        return (
            f"/mnt/data/parquet/nasa-firms/year={now.year}"
            f"/month={now.month:02d}/day={now.day:02d}/"
        )
