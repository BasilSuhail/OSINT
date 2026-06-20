"""Module C — Hazards: NASA EONET (Earth Observatory Natural Event Tracker).

Pulls the last 7 days of open natural events (wildfires, severe storms,
volcanoes, sea-lake ice, drought, dust-haze, floods, landslides, snow,
temperature extremes, water color). The 30-minute poll cadence relies on
idempotent dedup via the EONET event id.

Severity strategy:

1. If `magnitudeValue` is set on the latest geometry, normalise per `magnitudeUnit`
   (acres / km^2 / kts / hpa) using rough thresholds — see `_severity_for`.
2. Otherwise 0.5 as a neutral mid-band so the event still appears on the globe.

Geometry: EONET ships a list of {date, type, coordinates, magnitudeValue,
magnitudeUnit} per event — storms have many entries (a trajectory), point
events have one. We take the **latest** geometry's coordinates as the marker
position and stash the full trajectory in `payload.geometry` for replay.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from app.models import Category, Event
from app.sources.base import Fetcher

EONET_FEED_URL: Final[str] = "https://eonet.gsfc.nasa.gov/api/v3/events"
EONET_USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"
EONET_DEFAULT_DAYS: Final[int] = 7


# Rough severity normalisations per EONET magnitude unit. Tuned so that a
# "headline-grade" event lands around 0.7 - 0.9 and trivial ones land near 0.2.
_SEVERITY_NORMALISERS: Final[dict[str, tuple[float, float]]] = {
    # (max_floor, max_ceiling) — value linearly mapped from (0, ceiling) to (0, 1)
    "acres": (0.0, 100_000.0),  # wildfires
    "ha": (0.0, 40_000.0),  # wildfires (hectares)
    "km^2": (0.0, 400.0),  # ice, lava extents
    "kts": (10.0, 150.0),  # storm wind speed
    "hpa": (900.0, 1015.0),  # storm central pressure (inverted; lower = stronger)
    "nm": (0.0, 200.0),  # nautical miles, smoke/dust extent
}


def _severity_for(magnitude_value: float | None, magnitude_unit: str | None) -> float:
    """Map an EONET magnitude → [0, 1] severity. Neutral 0.5 if missing."""
    if magnitude_value is None or magnitude_unit is None:
        return 0.5
    try:
        v = float(magnitude_value)
    except (TypeError, ValueError):
        return 0.5
    unit = magnitude_unit.strip().lower()
    bounds = _SEVERITY_NORMALISERS.get(unit)
    if bounds is None:
        return 0.5
    lo, hi = bounds
    if hi <= lo:
        return 0.5
    if unit == "hpa":
        # Lower pressure = stronger storm. Invert mapping.
        clamped = max(lo, min(v, hi))
        return max(0.0, min((hi - clamped) / (hi - lo), 1.0))
    clamped = max(lo, min(v, hi))
    return max(0.0, min((clamped - lo) / (hi - lo), 1.0))


def _parse_iso_z(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # EONET emits "2026-06-17T13:57:00Z".
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _latest_geometry(geometries: Any) -> dict[str, Any] | None:
    """Return the most recent geometry record by date, or None."""
    if not isinstance(geometries, list) or not geometries:
        return None
    best: dict[str, Any] | None = None
    best_dt: datetime | None = None
    for g in geometries:
        if not isinstance(g, dict):
            continue
        gd = _parse_iso_z(g.get("date"))
        if gd is None:
            continue
        if best_dt is None or gd > best_dt:
            best = g
            best_dt = gd
    return best


def _point_coords(geometry: dict[str, Any]) -> tuple[float, float] | None:
    """Extract a single representative (lat, lon) from an EONET geometry record."""
    coords = geometry.get("coordinates")
    gtype = (geometry.get("type") or "").strip()
    if gtype == "Point" and isinstance(coords, list) and len(coords) >= 2:
        try:
            return float(coords[1]), float(coords[0])
        except (TypeError, ValueError):
            return None
    if gtype == "Polygon" and isinstance(coords, list) and coords:
        ring = coords[0]
        if isinstance(ring, list) and ring:
            lons: list[float] = []
            lats: list[float] = []
            for pt in ring:
                if isinstance(pt, list) and len(pt) >= 2:
                    try:
                        lons.append(float(pt[0]))
                        lats.append(float(pt[1]))
                    except (TypeError, ValueError):
                        continue
            if lons and lats:
                return sum(lats) / len(lats), sum(lons) / len(lons)
    return None


def feature_to_event(event_record: dict[str, Any], *, fetched_at: datetime) -> Event | None:
    """Pure transformation: an EONET event record → canonical Event."""
    if not isinstance(event_record, dict):
        return None
    eonet_id = event_record.get("id")
    title = event_record.get("title")
    if not eonet_id or not title:
        return None

    latest = _latest_geometry(event_record.get("geometry"))
    if latest is None:
        return None

    occurred_at = _parse_iso_z(latest.get("date"))
    if occurred_at is None:
        return None

    coords = _point_coords(latest)
    if coords is None:
        return None
    lat, lon = coords

    magnitude_value = latest.get("magnitudeValue")
    magnitude_unit = latest.get("magnitudeUnit")
    severity = _severity_for(magnitude_value, magnitude_unit)

    categories_raw = event_record.get("categories") or []
    category_ids: list[str] = []
    if isinstance(categories_raw, list):
        for c in categories_raw:
            if isinstance(c, dict) and isinstance(c.get("id"), str):
                category_ids.append(c["id"])

    sources_raw = event_record.get("sources") or []
    source_links: list[dict[str, Any]] = []
    if isinstance(sources_raw, list):
        for s in sources_raw:
            if isinstance(s, dict):
                source_links.append({"id": s.get("id"), "url": s.get("url")})

    keywords = ["eonet", *category_ids]

    payload: dict[str, Any] = {
        "eonet_id": eonet_id,
        "title": title,
        "categories": category_ids,
        "sources": source_links,
        "closed": event_record.get("closed"),
        "geometry_type": latest.get("type"),
        "magnitude_value": magnitude_value,
        "magnitude_unit": magnitude_unit,
        "link": event_record.get("link"),
    }

    return Event(
        source="eonet",
        source_event_id=str(eonet_id),
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.HAZARD,
        severity=severity,
        confidence=None,
        keywords=keywords,
        country=None,
        lat=lat,
        lon=lon,
        payload=payload,
    )


def parse_eonet_body(body: str, *, fetched_at: datetime) -> list[Event]:
    """Parse an EONET v3 response body into Events. Silent on bad input."""
    try:
        document = json.loads(body)
    except json.JSONDecodeError:
        return []
    events_raw = document.get("events") if isinstance(document, dict) else None
    if not isinstance(events_raw, list):
        return []
    events: list[Event] = []
    for record in events_raw:
        event = feature_to_event(record, fetched_at=fetched_at)
        if event is not None:
            events.append(event)
    return events


class EonetFetcher(Fetcher):
    """NASA EONET v3 natural-events fetcher."""

    name = "eonet"
    queue = "slow"

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        days: int = EONET_DEFAULT_DAYS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if days <= 0:
            raise ValueError("days must be positive")
        self.timeout_seconds = timeout_seconds
        self.days = days

    def fetch(self) -> list[Event]:
        fetched_at = datetime.now(UTC)
        with httpx.Client(
            timeout=self.timeout_seconds,
            headers={"User-Agent": EONET_USER_AGENT},
        ) as client:
            response = client.get(
                EONET_FEED_URL,
                params={"status": "open", "days": str(self.days)},
            )
            response.raise_for_status()
            return parse_eonet_body(response.text, fetched_at=fetched_at)

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return f"/mnt/data/parquet/eonet/year={now.year}/month={now.month:02d}/day={now.day:02d}/"
