"""When a satellite will next be overhead a point (#876).

The place screen shows the newest low-cloud photograph of a spot with its
capture date. What it could not say is *why* that date is what it is. Nine days
old means one of two very different things — the satellite has not passed, or
it has passed four times and every pass was cloudy — and the reader had no way
to tell whether waiting would help.

This answers the first half: when the spacecraft is next overhead. It produces
no events, writes no rows, and stores nothing. Orbital elements are a few
kilobytes, refreshed daily and held in memory; the propagation is arithmetic.

A note on what "overhead" means here, because two clocks are involved. The
capture timestamp on a product is the sensing start of the whole datastrip, and
a datastrip is long. Measured against three known captures over one point, the
spacecraft reaches that point a consistent 650-690 seconds after the timestamp
the archive prints. So a predicted pass time and an archive timestamp for the
same overflight differ by roughly eleven minutes, and neither is wrong. At the
resolution this is displayed — "next pass in 2 days" — the difference does not
survive rounding, but it would matter to anyone comparing the two directly.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime, timedelta

import httpx
from sgp4.api import Satrec, jday

#: Public, keyless, and refreshed on their side several times a day.
_ELEMENTS_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=resource&FORMAT=tle"

#: Elements decay slowly; a day-old set is accurate to well under the tolerance
#: of "in about two days".
_ELEMENTS_TTL_S = 24 * 3600

_TIMEOUT_S = 8.0
_USER_AGENT = "OSINT-console/1.0 (https://github.com/BasilSuhail/OSINT)"

#: Sentinel-2 images a 290 km swath centred on the ground track, so a point is
#: imaged when the sub-satellite point comes within half of that. Only the two
#: (now three) Sentinel-2 spacecraft are propagated: the screen's question is
#: about the imagery it is showing, and every other satellite would answer a
#: question nobody asked.
_SWATH_HALF_KM = 145.0
_PLATFORM_PREFIX = "SENTINEL-2"

#: Sun-synchronous and retrograde at 98.57 degrees, so the ground track turns
#: back below about 81 degrees of latitude. Points nearer the poles than that
#: are never overflown, and the honest answer for them is nothing rather than a
#: pass invented to fill the line.

#: Optical imaging needs daylight. Five degrees rather than zero keeps out the
#: grazing twilight passes that produce nothing usable.
_MIN_SUN_ELEVATION_DEG = 5.0

#: Half a minute of ground track is about 200 km, comfortably inside the swath,
#: so no overflight can fall between two samples.
_STEP_S = 30
_HORIZON_DAYS = 6

#: One overflight cannot immediately be followed by another; skipping ahead
#: stops a single pass being reported as several.
_PASS_COOLDOWN_S = 40 * 60

_EARTH_RADIUS_KM = 6371.0

_cache: dict[str, tuple[float, list[tuple[str, Satrec]]]] = {}


def clear_cache() -> None:
    """Forget the held elements. Tests need this; nothing else does."""
    _cache.clear()


def parse_elements(text: str) -> list[tuple[str, Satrec]]:
    """Pull the Sentinel-2 spacecraft out of a three-line-per-object listing."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    found: list[tuple[str, Satrec]] = []
    for i in range(len(lines) - 2):
        name = lines[i].strip()
        if not name.startswith(_PLATFORM_PREFIX):
            continue
        first, second = lines[i + 1], lines[i + 2]
        #: Length is checked because the propagator does not check anything: it
        #: accepts "1 garbage" without complaint and returns an object that
        #: propagates to nonsense. A real element line is 69 characters.
        if not (first.startswith("1 ") and second.startswith("2 ")):
            continue
        if len(first) < 69 or len(second) < 69:
            continue
        try:
            found.append((name, Satrec.twoline2rv(lines[i + 1], lines[i + 2])))
        except Exception:
            # A malformed element set is skipped, never guessed at.
            continue
    return found


def _elements(client: httpx.Client | None = None) -> list[tuple[str, Satrec]]:
    hit = _cache.get("elements")
    now = time.monotonic()
    if hit is not None and now - hit[0] < _ELEMENTS_TTL_S:
        return hit[1]
    owned = client is None
    http = client or httpx.Client(timeout=_TIMEOUT_S, headers={"User-Agent": _USER_AGENT})
    try:
        response = http.get(_ELEMENTS_URL)
        response.raise_for_status()
        parsed = parse_elements(response.text)
    finally:
        if owned:
            http.close()
    if not parsed:
        raise LookupError("no Sentinel-2 elements in the published set")
    _cache["elements"] = (now, parsed)
    return parsed


def _gmst_rad(jd: float, fr: float) -> float:
    """Greenwich mean sidereal time — how far the Earth has turned under the orbit."""
    days = jd + fr - 2451545.0
    centuries = days / 36525.0
    degrees = (
        280.46061837
        + 360.98564736629 * days
        + 0.000387933 * centuries**2
        - centuries**3 / 38710000.0
    )
    return math.radians(degrees % 360.0)


def _subpoint(sat: Satrec, when: datetime) -> tuple[float, float] | None:
    """Latitude and longitude the spacecraft is directly above."""
    jd, fr = jday(
        when.year,
        when.month,
        when.day,
        when.hour,
        when.minute,
        when.second + when.microsecond / 1e6,
    )
    code, position, _velocity = sat.sgp4(jd, fr)
    if code != 0:
        return None
    x, y, z = position
    theta = _gmst_rad(jd, fr)
    # The propagator works in an inertial frame; the Earth has turned under it.
    x_fixed = x * math.cos(theta) + y * math.sin(theta)
    y_fixed = -x * math.sin(theta) + y * math.cos(theta)
    lon = math.degrees(math.atan2(y_fixed, x_fixed))
    lat = math.degrees(math.atan2(z, math.hypot(x_fixed, y_fixed)))
    return lat, (lon + 180.0) % 360.0 - 180.0


def ground_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    delta = math.radians(lon2 - lon1)
    cosine = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(delta)
    return _EARTH_RADIUS_KM * math.acos(max(-1.0, min(1.0, cosine)))


def sun_elevation_deg(lat: float, lon: float, when: datetime) -> float:
    """How high the sun is, which decides whether an optical pass sees anything."""
    days = (when - datetime(2000, 1, 1, 12, tzinfo=UTC)).total_seconds() / 86400.0
    mean_lon = math.radians((280.460 + 0.9856474 * days) % 360.0)
    anomaly = math.radians((357.528 + 0.9856003 * days) % 360.0)
    ecliptic_lon = (
        mean_lon
        + math.radians(1.915) * math.sin(anomaly)
        + math.radians(0.020) * math.sin(2 * anomaly)
    )
    obliquity = math.radians(23.439 - 0.0000004 * days)
    declination = math.asin(math.sin(obliquity) * math.sin(ecliptic_lon))
    sidereal_h = (18.697374558 + 24.06570982441908 * days) % 24.0
    right_ascension = math.atan2(
        math.cos(obliquity) * math.sin(ecliptic_lon), math.cos(ecliptic_lon)
    )
    hour_angle = math.radians((sidereal_h * 15.0 + lon) % 360.0) - right_ascension
    phi = math.radians(lat)
    altitude = math.asin(
        math.sin(phi) * math.sin(declination)
        + math.cos(phi) * math.cos(declination) * math.cos(hour_angle)
    )
    return math.degrees(altitude)


def next_overpass(
    lat: float,
    lon: float,
    *,
    after: datetime | None = None,
    client: httpx.Client | None = None,
) -> dict | None:
    """The next daylight overflight of this point, or None within the horizon.

    Returns the moment the spacecraft is overhead, which platform it is, and
    how far off it is — not a promise of a photograph. Whether anything usable
    comes back depends on cloud, and no amount of orbital mechanics predicts
    that.
    """
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    start = after or datetime.now(UTC)
    horizon = start + timedelta(days=_HORIZON_DAYS)
    step = timedelta(seconds=_STEP_S)

    best: tuple[datetime, str] | None = None
    for name, sat in _elements(client):
        when = start
        while when < horizon:
            if best is not None and when >= best[0]:
                break
            point = _subpoint(sat, when)
            if point is None:
                when += step
                continue
            if ground_distance_km(lat, lon, point[0], point[1]) < _SWATH_HALF_KM:
                if sun_elevation_deg(lat, lon, when) > _MIN_SUN_ELEVATION_DEG:
                    if best is None or when < best[0]:
                        best = (when, name)
                    break
                when += timedelta(seconds=_PASS_COOLDOWN_S)
                continue
            when += step

    if best is None:
        return None
    at, platform = best
    return {
        "at": at.replace(microsecond=0).isoformat(),
        "platform": platform.title().replace("Sentinel-2", "Sentinel-2"),
        "hours_away": round((at - start).total_seconds() / 3600.0, 1),
    }
