"""OpenSky public ADS-B flight-density fetcher.

OpenSky Network publishes a free no-key endpoint at ``/api/states/all``
returning every aircraft broadcasting ADS-B in the last ~10 s.

Until #496 each state vector was stored as its own ``Event``. That cost
~190k rows/day — 96% of the events table, roughly 6.5 GB — and fed nothing:
the rows carried no ``country``, and ``daily_side_counts`` only ever matches
rows by country, so divergence silently skipped every one of them. The
dashboard did not render them either.

The fetcher now aggregates. Each poll resolves every aircraft to an ISO
country and emits one ``Event`` per country per hour, carrying aircraft
counts in ``payload``. ``source_event_id`` is keyed to the hour, so the
upsert refreshes an existing row rather than appending — an hour of polling
costs one row per country, whatever the cadence.

Severity is 0: aviation activity isn't stress, it's situational awareness.

Note that divergence still counts *rows*, so this feed contributes a constant
per country until scoring learns to weight by ``aircraft_count`` — see #497.

See issues #160, #496.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import httpx

from app.enrichment.country import country_for
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


def _aircraft_position(state: list[Any]) -> tuple[str, float, float, bool] | None:
    """Pull ``(icao24, lat, lon, on_ground)`` from one state vector, or None."""
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
    return str(icao24), lat_f, lon_f, bool(state[_IDX_ON_GROUND])


def _hour_floor(moment: datetime) -> datetime:
    """Truncate to the top of the hour, in UTC."""
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def parse_opensky_body(body: dict[str, Any], *, fetched_at: datetime) -> list[Event]:
    """Pure transformation: OpenSky JSON → per-country hourly density Events.

    Aircraft over open water (or anywhere the 110 m Natural Earth set does not
    resolve) are dropped: without a country they cannot reach any consumer.
    """
    states = body.get("states") or []
    hour = _hour_floor(fetched_at)

    # icao24 sets, so an airframe repeated within one response counts once.
    airborne: dict[str, set[str]] = {}
    grounded: dict[str, set[str]] = {}
    for state in states:
        parsed = _aircraft_position(state)
        if parsed is None:
            continue
        icao24, lat, lon, on_ground = parsed
        iso = country_for(lat, lon)
        if iso is None:
            continue
        bucket = grounded if on_ground else airborne
        bucket.setdefault(iso, set()).add(icao24)

    out: list[Event] = []
    for iso in sorted(set(airborne) | set(grounded)):
        up = airborne.get(iso, set())
        down = grounded.get(iso, set())
        distinct = up | down
        out.append(
            Event(
                source="opensky-adsb",
                source_event_id=f"{iso}|{hour:%Y-%m-%dT%H}",
                occurred_at=hour,
                fetched_at=fetched_at,
                category=Category.TRACKING,
                severity=0.0,
                confidence=None,
                keywords=["adsb", "aircraft", "flight-density"],
                country=iso,
                lat=None,  # a country aggregate has no single position
                lon=None,
                payload={
                    "aircraft_count": len(distinct),
                    "airborne_count": len(up - down),
                    "on_ground_count": len(down),
                    "sampled_at": fetched_at.isoformat(),
                },
            )
        )
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
