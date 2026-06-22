"""OpenSky public ADS-B aircraft state fetcher.

OpenSky Network publishes a free no-key endpoint at
``/api/states/all`` returning every aircraft broadcasting ADS-B in
the last ~10 s. Rate-limited per anonymous IP — 10 s is the floor
on the cadence; we poll every ~2 min to stay polite.

Each state row is normalised to one canonical ``Event`` with
``category = Category.TRACKING``. The full OpenSky tuple is stashed
in ``payload`` for replay. Severity is 0 — aviation activity isn't
stress; it's situational awareness. The dashboard renders these in
their own colour band via the existing source-key path.

See issue #160.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import httpx

from app.models import Category, Event
from app.sources.base import Fetcher

OPENSKY_URL: Final[str] = "https://opensky-network.org/api/states/all"
OPENSKY_USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"

# OpenSky's state vector position is documented at
# https://openskynetwork.github.io/opensky-api/rest.html#all-state-vectors
# 0:icao24, 1:callsign, 2:origin_country, 3:time_position, 4:last_contact,
# 5:longitude, 6:latitude, 7:baro_altitude, 8:on_ground, 9:velocity,
# 10:true_track, 11:vertical_rate, ..., 13:geo_altitude
_IDX_ICAO24: Final[int] = 0
_IDX_CALLSIGN: Final[int] = 1
_IDX_ORIGIN_COUNTRY: Final[int] = 2
_IDX_TIME_POSITION: Final[int] = 3
_IDX_LON: Final[int] = 5
_IDX_LAT: Final[int] = 6
_IDX_BARO_ALT: Final[int] = 7
_IDX_ON_GROUND: Final[int] = 8
_IDX_VELOCITY: Final[int] = 9
_IDX_TRUE_TRACK: Final[int] = 10
_IDX_VERTICAL_RATE: Final[int] = 11
_IDX_GEO_ALT: Final[int] = 13


def _state_to_event(state: list[Any], fetched_at: datetime) -> Event | None:
    """Normalise one OpenSky state vector to an ``Event``. None on bad data."""
    if not state or len(state) < 14:
        return None
    icao24 = state[_IDX_ICAO24]
    lat = state[_IDX_LAT]
    lon = state[_IDX_LON]
    if not icao24 or lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None
    time_pos = state[_IDX_TIME_POSITION]
    if isinstance(time_pos, int):
        occurred_at = datetime.fromtimestamp(time_pos, tz=UTC)
    else:
        occurred_at = fetched_at
    callsign = (state[_IDX_CALLSIGN] or "").strip() if state[_IDX_CALLSIGN] else None
    origin = state[_IDX_ORIGIN_COUNTRY] or None

    payload = {
        "icao24": str(icao24),
        "callsign": callsign,
        "origin_country": origin,
        "baro_altitude_m": state[_IDX_BARO_ALT],
        "geo_altitude_m": state[_IDX_GEO_ALT],
        "on_ground": bool(state[_IDX_ON_GROUND]),
        "velocity_m_s": state[_IDX_VELOCITY],
        "true_track_deg": state[_IDX_TRUE_TRACK],
        "vertical_rate_m_s": state[_IDX_VERTICAL_RATE],
    }

    return Event(
        source="opensky-adsb",
        source_event_id=f"{icao24}|{int(occurred_at.timestamp())}",
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.TRACKING,
        severity=0.0,
        confidence=None,
        keywords=["adsb", "aircraft", "tracking"],
        country=None,  # origin_country is free-text, not ISO; left null
        lat=lat_f,
        lon=lon_f,
        payload=payload,
    )


def parse_opensky_body(body: dict[str, Any], *, fetched_at: datetime) -> list[Event]:
    """Pure transformation: OpenSky JSON → list of canonical Events."""
    states = body.get("states") or []
    out: list[Event] = []
    for state in states:
        ev = _state_to_event(state, fetched_at=fetched_at)
        if ev is not None:
            out.append(ev)
    return out


class OpenSkyFetcher(Fetcher):
    name = "opensky-adsb"
    queue = "fast"

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> list[Event]:
        fetched_at = datetime.now(UTC)
        with httpx.Client(
            timeout=self.timeout_seconds,
            headers={"User-Agent": OPENSKY_USER_AGENT, "Accept": "application/json"},
        ) as client:
            response = client.get(OPENSKY_URL)
            response.raise_for_status()
            return parse_opensky_body(response.json(), fetched_at=fetched_at)

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return (
            f"/mnt/data/parquet/opensky-adsb/year={now.year}"
            f"/month={now.month:02d}/day={now.day:02d}/"
        )
