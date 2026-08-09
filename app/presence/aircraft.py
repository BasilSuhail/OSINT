"""Military and emergency aircraft, live and unstored (#873).

Two lists from one aggregator, merged: aircraft flagged military, and aircraft
squawking a distress code. Not all traffic — the ones worth knowing about.
Measured live while this was written: 106 military aircraft airborne worldwide,
69 of them positioned, 42 KB for the lot. The whole planet fits in one request,
so there is no viewport parameter and nothing to page.

Every field except position is optional, and the counts are not close to full.
In one measured sample of 66 positioned aircraft: track on 62, type on 65,
registration on 65, callsign on 58, squawk on 56. Absent is rendered as absent
rather than filled in.

Direction comes from ``track``, the course made good over the ground, because
``true_heading`` was present on 5 of those 66. A design resting on the heading
field would have drawn nothing almost every time.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.presence.registry import PresenceSource, source_for

#: Distress codes. 7500 hijack, 7600 lost radio, 7700 general emergency. All
#: three read zero most of the time, which is what makes a non-zero one worth
#: a louder mark on the map than any amount of routine traffic.
DISTRESS_SQUAWKS: frozenset[str] = frozenset({"7500", "7600", "7700"})

_TIMEOUT_S = 8.0
_USER_AGENT = "OSINT-console/1.0 (https://github.com/BasilSuhail/OSINT)"

#: Which distress code to check on this refresh. All three are polled in turn
#: rather than every time: four requests per refresh earned a 429 from a free
#: community service on the first live run, and one refused request should not
#: cost the whole picture. Distress persists for minutes, so a code checked
#: every third refresh is checked often enough.
_rotation = 0

_cache: dict[str, tuple[float, dict]] = {}


def _new_client() -> httpx.Client:
    """The outbound client, in one place so a test can replace it.

    Patching httpx itself would also gag the test client, which is built on it,
    and the test would then be measuring its own plumbing.
    """
    return httpx.Client(timeout=_TIMEOUT_S, headers={"User-Agent": _USER_AGENT})


def clear_cache() -> None:
    """Forget what is held in memory. Tests need this; nothing else does."""
    global _rotation
    _cache.clear()
    _rotation = 0


def _number(value: Any) -> float | None:
    """A count that is not a number is absent, never zero.

    Altitude arrives as the string "ground" for an aircraft that is not flying,
    and zero would be a different and wrong claim.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def is_distressed(row: dict) -> bool:
    """Whether this aircraft is announcing trouble."""
    if _text(row.get("squawk")) in DISTRESS_SQUAWKS:
        return True
    emergency = _text(row.get("emergency"))
    return emergency is not None and emergency.lower() not in {"none", "no"}


def normalise(row: dict, *, kind: str) -> dict | None:
    """One aircraft, or None when there is nothing to draw.

    ``t`` is the aircraft type — C30J, AS65. ``type`` is the *message* type,
    "adsb_icao", and reading it here would label every mark identically.
    """
    lat, lon = _number(row.get("lat")), _number(row.get("lon"))
    if lat is None or lon is None:
        return None
    return {
        "hex": _text(row.get("hex")),
        "callsign": _text(row.get("flight")),
        "type": _text(row.get("t")),
        "registration": _text(row.get("r")),
        "lat": lat,
        "lon": lon,
        "track": _number(row.get("track")),
        "alt_ft": _number(row.get("alt_baro")),
        "speed_kt": _number(row.get("gs")),
        "squawk": _text(row.get("squawk")),
        "kind": kind,
    }


def merge(military: list[dict], distressed: list[dict]) -> list[dict]:
    """Both lists, deduped by transponder address, distress winning.

    A military aircraft squawking 7700 is one aircraft with two reasons to be
    on the map, and the urgent reason is the one worth drawing.
    """
    by_hex: dict[str, dict] = {}
    for row in military:
        item = normalise(row, kind="distress" if is_distressed(row) else "military")
        if item and item["hex"]:
            by_hex[item["hex"]] = item
    for row in distressed:
        item = normalise(row, kind="distress")
        if item and item["hex"]:
            by_hex[item["hex"]] = item
    return sorted(by_hex.values(), key=lambda a: (a["kind"] != "distress", a["hex"]))


def _get_json(client: httpx.Client, source: PresenceSource, path: str) -> dict:
    """Try each endpoint in turn; the last failure is the one that surfaces.

    Only endpoints whose terms have actually been read are configured, so a
    mirror is a one-line addition rather than a code change.
    """
    last: Exception | None = None
    for base in source.endpoints:
        try:
            response = client.get(f"{base}{path}")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("expected an object")
            return payload
        except Exception as exc:
            last = exc
    raise last or LookupError("no endpoint configured")


def _fetch(client: httpx.Client, source: PresenceSource) -> dict:
    """Two requests: the military list, and one distress code in rotation.

    Partial failure is kept partial. A refused squawk check must not discard a
    military list that arrived intact — losing a hundred aircraft because one
    rare-by-design query was rate-limited is a worse answer than a slightly
    incomplete one, and the response says which happened.
    """
    global _rotation

    degraded = False
    military: list[dict] = []
    try:
        military = _get_json(client, source, "/v2/mil").get("ac") or []
    except Exception:
        degraded = True

    codes = sorted(DISTRESS_SQUAWKS)
    code = codes[_rotation % len(codes)]
    _rotation += 1
    distressed: list[dict] = []
    try:
        distressed = _get_json(client, source, f"/v2/sqk/{code}").get("ac") or []
    except Exception:
        degraded = True

    #: A distressed *military* aircraft needs no extra request: the military
    #: payload already carries squawk and emergency on every row, and `merge`
    #: reads them.
    aircraft = merge(military, distressed)
    return {
        "fetched_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "count": len(aircraft),
        "aircraft": aircraft,
        "degraded": degraded,
    }


def live_aircraft(*, client: httpx.Client | None = None) -> dict:
    """The current picture, or an honest blank.

    When nothing answers, the result is empty and says so. The alternative —
    holding the last positions on screen — presents minutes-old locations as
    current, which is the one thing a live layer must never do.
    """
    source = source_for("aircraft")
    hit = _cache.get("aircraft")
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

    #: An empty degraded picture is never cached: pinning "nothing" in place for
    #: the whole window would turn one refused request into half a minute of
    #: blank map.
    if not (answer["degraded"] and answer["count"] == 0):
        _cache["aircraft"] = (now, answer)
    return answer
