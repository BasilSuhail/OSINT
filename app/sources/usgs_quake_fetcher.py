"""Module C — Hazards: USGS earthquakes via the 4.5+ daily GeoJSON feed.

Pulls earthquakes of magnitude 4.5 and above over the last 24 hours. The 15-minute
poll cadence relies on idempotent dedup (USGS event id) to handle re-ingestion.

Severity priority:

1. If the PAGER alert level is set, use it (red/orange/yellow/green → 1/0.75/0.5/0.25).
2. Otherwise scale magnitude linearly: severity = clamp((mag - 3) / 7, 0, 1) so M3
   = 0 and M10 = 1.

Country tagging via reverse-geocoding is deferred; lat/lon are stored on the
event so the composite worker can spatially join later.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Final

import httpx

from app.enrichment.country import country_for
from app.models import Category, Event
from app.sources.base import Fetcher

USGS_FEED_URL: Final[str] = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"
)
USGS_USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"

_PAGER_ALERT_SEVERITY: Final[dict[str, float]] = {
    "red": 1.0,
    "orange": 0.75,
    "yellow": 0.5,
    "green": 0.25,
}


def _magnitude_to_severity(magnitude: float) -> float:
    return max(0.0, min((magnitude - 3.0) / 7.0, 1.0))


def feature_to_event(feature: dict[str, Any], *, fetched_at: datetime) -> Event | None:
    """Pure transformation: a GeoJSON quake feature → canonical Event."""
    if not isinstance(feature, dict):
        return None

    event_id = feature.get("id")
    properties = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []

    if not event_id or not properties:
        return None

    time_ms = properties.get("time")
    magnitude = properties.get("mag")
    if time_ms is None or magnitude is None:
        return None

    try:
        magnitude_f = float(magnitude)
    except (TypeError, ValueError):
        return None

    try:
        occurred_at = datetime.fromtimestamp(int(time_ms) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None

    alert = (properties.get("alert") or "").strip().lower() or None
    if alert in _PAGER_ALERT_SEVERITY:
        severity = _PAGER_ALERT_SEVERITY[alert]
    else:
        severity = _magnitude_to_severity(magnitude_f)

    lon: float | None = None
    lat: float | None = None
    if isinstance(coordinates, list) and len(coordinates) >= 2:
        try:
            lon = float(coordinates[0])
            lat = float(coordinates[1])
        except (TypeError, ValueError):
            lon = lat = None

    payload: dict[str, Any] = {
        "usgs_id": event_id,
        "place": properties.get("place"),
        "magnitude": magnitude_f,
        "depth_km": coordinates[2] if len(coordinates) >= 3 else None,
        "tsunami": properties.get("tsunami"),
        "felt": properties.get("felt"),
        "alert": alert,
    }

    country = country_for(lat, lon) if lat is not None and lon is not None else None

    return Event(
        source="usgs-quake",
        source_event_id=str(event_id),
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.HAZARD,
        severity=severity,
        confidence=None,
        keywords=["usgs", "earthquake", f"m{int(magnitude_f)}"],
        country=country,
        lat=lat,
        lon=lon,
        payload=payload,
    )


def parse_geojson_body(body: str, *, fetched_at: datetime) -> list[Event]:
    """Parse a USGS earthquake GeoJSON feed body into Events.

    Drops malformed features silently — never raises on bad data.
    """
    try:
        document = json.loads(body)
    except json.JSONDecodeError:
        return []

    features = document.get("features") or []
    if not isinstance(features, list):
        return []

    events: list[Event] = []
    for feature in features:
        event = feature_to_event(feature, fetched_at=fetched_at)
        if event is not None:
            events.append(event)
    return events


class UsgsQuakeFetcher(Fetcher):
    """USGS 4.5+ daily earthquake fetcher."""

    name = "usgs-quake"
    queue = "slow"

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> list[Event]:
        fetched_at = datetime.now(timezone.utc)
        with httpx.Client(
            timeout=self.timeout_seconds, headers={"User-Agent": USGS_USER_AGENT}
        ) as client:
            response = client.get(USGS_FEED_URL)
            response.raise_for_status()
            return parse_geojson_body(response.text, fetched_at=fetched_at)

    def archive_path(self) -> str:
        now = datetime.now(timezone.utc)
        return (
            f"/mnt/data/parquet/usgs-quake/year={now.year}/month={now.month:02d}/day={now.day:02d}/"
        )
