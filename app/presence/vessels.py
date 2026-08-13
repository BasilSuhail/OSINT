"""Vessels broadcasting AIS, live and unstored (#954).

Two requests to one open feed: where every vessel is, and what every vessel is.
The position message and the static message are separate on the wire and
separate here, joined by MMSI, because that is how AIS itself works — a vessel
transmits its position every few seconds and its name every few minutes, and a
vessel heard once may have one without the other.

**Coverage is receiver coverage, and it is coastal.** The feed is a national
authority's terrestrial receiver network. It sees its own sea area well and the
open ocean not at all, and no part of this layer may imply otherwise: an empty
Atlantic on this map is an empty receiver map, not an empty ocean. Satellite
AIS, which would see the rest, is a paid product and is not used.

Measured live on 2026-08-13: 1,261 positions and 1,203 static rows, every one
of the latter carrying a name. Ship type on all of them, which is why the
filter rows are read off the wire rather than inferred.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.presence import vessels_no
from app.presence.registry import PresenceSource, source_for
from app.presence.vessel_types import category_for, nav_status_for

_TIMEOUT_S = 10.0
_USER_AGENT = "OSINT-console/1.0 (https://github.com/BasilSuhail/OSINT)"

#: A position older than this is not "now". Vessels are slow, so the tolerance
#: is wider than an aircraft's — a ship reports every few seconds under way but
#: only every few minutes at anchor, and dropping those would empty every
#: harbour on the map.
_MAX_POSITION_AGE_S = 60 * 60

_cache: dict[str, tuple[float, dict]] = {}


def _new_client() -> httpx.Client:
    """The outbound client, in one place so a test can replace it."""
    return httpx.Client(timeout=_TIMEOUT_S, headers={"User-Agent": _USER_AGENT})


def clear_cache() -> None:
    """Forget what is held in memory. Tests need this; nothing else does."""
    _cache.clear()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _course(value: Any) -> float | None:
    """A course or heading, or nothing.

    AIS sends 511 for "heading not available" and 360 for "course not
    available". Drawn as a number, either would point a hull at a direction
    nobody transmitted.
    """
    number = _number(value)
    if number is None or number < 0 or number >= 360:
        return None
    return number


def normalise(feature: dict, static: dict | None, *, now_ms: float) -> dict | None:
    """One vessel, or None when there is nothing to draw.

    A position with no static row is still a vessel and is still drawn — it is
    really out there — with no name and no category. A static row with no
    position is dropped: there is nothing to put on a map.
    """
    if not isinstance(feature, dict):
        return None
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        return None
    lon, lat = _number(coordinates[0]), _number(coordinates[1])
    if lat is None or lon is None:
        return None

    props = feature.get("properties") or {}
    reported_ms = _number(props.get("timestampExternal"))
    if reported_ms is not None and (now_ms - reported_ms) > _MAX_POSITION_AGE_S * 1000:
        return None

    mmsi = _int(props.get("mmsi")) or _int(feature.get("mmsi"))
    ship_type = _int((static or {}).get("shipType"))
    #: Zero is the standard's "not available", and reading it as a type would
    #: file a silent vessel under a category it never claimed.
    ship_type = ship_type or None

    return {
        "mmsi": mmsi,
        "name": _text((static or {}).get("name")),
        "callsign": _text((static or {}).get("callSign")),
        "imo": _int((static or {}).get("imo")) or None,
        "lat": lat,
        "lon": lon,
        "speed_kt": _number(props.get("sog")),
        "course": _course(props.get("cog")),
        "heading": _course(props.get("heading")),
        "nav_status": nav_status_for(_int(props.get("navStat"))),
        "category": category_for(ship_type),
        "ship_type": ship_type,
        "destination": _text((static or {}).get("destination")),
        "position_accurate": bool(props.get("posAcc")) if "posAcc" in props else None,
        #: Filled in by `flag_spoofed` once every vessel in the refresh is
        #: known: one of the two tests needs to see the others.
        "position_suspect": None,
        "reported_at": (
            datetime.fromtimestamp(reported_ms / 1000, UTC).replace(microsecond=0).isoformat()
            if reported_ms is not None
            else None
        ),
    }


#: No ship goes this fast. The fastest passenger craft in service run to about
#: 45 knots and everything else is far slower, so a hull reporting 46 knots is
#: not reporting where it is.
IMPLAUSIBLE_SPEED_KT = 40.0

#: Coordinates rounded to this many decimals — about a hundred metres — before
#: looking for a pile-up. Two vessels genuinely moored abreast are metres
#: apart; a spoofer puts many of them on one point.
_STACK_DECIMALS = 3

#: How many hulls on one point stop being a coincidence. Three is already
#: impossible for anything under way.
_STACK_MIN = 3

#: Only vessels making way are counted into a pile-up. Moored craft genuinely
#: do share a point — a row of pilot boats at one pier rounds to one set of
#: coordinates, and the first version of this test accused every marina in the
#: sea area. Hulls that are *moving* cannot occupy the same hundred metres.
_STACK_MOVING_KT = 5.0


def flag_spoofed(rows: list[dict]) -> list[dict]:
    """Mark positions the console does not believe, and say why.

    Not dropped, and this is deliberate. A transmitter claiming to be a ship
    in the middle of a forest is a real thing that is really happening, and it
    is worth more to a reader than the traffic around it — interference of
    this kind is a finding, not noise. What would be dishonest is drawing it
    like an ordinary vessel, so the mark says it is not trusted and the card
    says which test it failed.

    Two tests, both from what the feed itself sent:

    ``speed`` — a reported speed no vessel can reach.

    ``stacked`` — several hulls sharing one position to within about a hundred
    metres. Measured live on 2026-08-13: eight vessels on a single point far
    inland, reporting 35 to 51 knots, every one of them with the position
    accuracy flag set to false.
    """

    def moving(row: dict) -> bool:
        speed = row.get("speed_kt")
        return speed is not None and speed >= _STACK_MOVING_KT

    buckets: dict[tuple[float, float], int] = {}
    for row in rows:
        if not moving(row):
            continue
        key = (round(row["lat"], _STACK_DECIMALS), round(row["lon"], _STACK_DECIMALS))
        buckets[key] = buckets.get(key, 0) + 1

    for row in rows:
        key = (round(row["lat"], _STACK_DECIMALS), round(row["lon"], _STACK_DECIMALS))
        speed = row.get("speed_kt")
        #: Stacking is the stronger evidence, so it is the reason that shows.
        if moving(row) and buckets.get(key, 0) >= _STACK_MIN:
            row["position_suspect"] = "stacked"
        elif speed is not None and speed >= IMPLAUSIBLE_SPEED_KT:
            row["position_suspect"] = "speed"
        else:
            #: Set on every row, not only the suspect ones: a key that appears
            #: when there is bad news and is missing otherwise is a key every
            #: reader of this data has to remember to check for.
            row["position_suspect"] = None
    return rows


def merge(positions: dict, statics: list[dict], *, now_ms: float | None = None) -> list[dict]:
    """Positions, each carrying whatever static data arrived for the same MMSI.

    Deduped by MMSI: a feed that repeats a vessel is describing one vessel, and
    two marks for one hull would be counted twice by every reader looking at
    the map.
    """
    stamp = time.time() * 1000 if now_ms is None else now_ms
    by_mmsi: dict[int, dict] = {}
    for row in statics:
        key = _int(row.get("mmsi")) if isinstance(row, dict) else None
        if key is not None:
            by_mmsi[key] = row

    out: dict[int | None, dict] = {}
    features = positions.get("features") if isinstance(positions, dict) else None
    for feature in features or []:
        props = (feature or {}).get("properties") or {}
        key = _int(props.get("mmsi")) or _int((feature or {}).get("mmsi"))
        item = normalise(feature, by_mmsi.get(key) if key is not None else None, now_ms=stamp)
        if item is None:
            continue
        out[item["mmsi"]] = item
    return sorted(
        flag_spoofed(list(out.values())),
        key=lambda v: (v["mmsi"] is None, v["mmsi"] or 0),
    )


def _get_json(client: httpx.Client, source: PresenceSource, path: str) -> Any:
    """Try each endpoint in turn; the last failure is the one that surfaces."""
    last: Exception | None = None
    for base in source.endpoints:
        try:
            response = client.get(f"{base}{path}")
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last = exc
    raise last or LookupError("no endpoint configured")


def _fetch(client: httpx.Client, source: PresenceSource) -> dict:
    """Positions and static data, with partial failure kept partial.

    Losing the names is not losing the vessels. A refused static request leaves
    a map of unnamed marks, which is worse than a named one and far better than
    an empty one, and the response says `degraded` so the map can say so too.
    """
    degraded = False
    attributions: list[str] = []
    positions: dict = {}
    try:
        payload = _get_json(client, source, "/api/ais/v1/locations")
        positions = payload if isinstance(payload, dict) else {}
        attributions.append(source.attribution)
    except Exception:
        degraded = True

    statics: list[dict] = []
    try:
        payload = _get_json(client, source, "/api/ais/v1/vessels")
        statics = (
            [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []
        )
    except Exception:
        degraded = True

    #: The second sea area, when it is configured (#954). Its rows are
    #: reshaped into this feed's shape on the way in, so the categories, the
    #: join, the spoofing tests and the age cut are written once and every
    #: source is held to them.
    #:
    #: No credentials is not degradation. The layer is not asking, which is a
    #: different thing from asking and being refused, and saying "degraded"
    #: for a source nobody configured would cry wolf on every console that
    #: only wants the first sea.
    if vessels_no.credentials() is not None:
        try:
            no_source = source_for("vessels_no")
            features, no_statics = vessels_no.fetch(
                client, no_source.endpoints[0], "/v1/latest/combined"
            )
            existing = positions.get("features") if isinstance(positions, dict) else None
            positions = {
                "type": "FeatureCollection",
                "features": [*(existing or []), *features],
            }
            statics = [*statics, *no_statics]
            if features:
                attributions.append(no_source.attribution)
        except Exception:
            degraded = True

    vessels = merge(positions, statics)
    return {
        "fetched_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "count": len(vessels),
        "sources": attributions,
        "vessels": vessels,
        "degraded": degraded,
    }


def live_vessels(*, client: httpx.Client | None = None) -> dict:
    """The current picture, or an honest blank.

    When nothing answers, the result is empty and says so. Holding the last
    positions on screen would present a ship where it was an hour ago as where
    it is, which is the one thing a live layer must never do.
    """
    source = source_for("vessels")
    hit = _cache.get("vessels")
    now = time.monotonic()
    if hit is not None and now - hit[0] < source.ttl_s:
        return hit[1]

    owned = client is None
    http = client or _new_client()
    try:
        answer = _fetch(http, source)
    finally:
        if owned:
            http.close()

    #: An empty degraded picture is never cached: pinning "nothing" in place
    #: would turn one refused request into a minute of blank sea.
    if not (answer["degraded"] and answer["count"] == 0):
        _cache["vessels"] = (now, answer)
    return answer
