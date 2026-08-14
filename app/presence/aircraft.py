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
from app.presence.watchlist import (
    EMPTY_WATCHLIST,
    Watchlist,
    forget_stale,
    note_airborne,
    resolve_watchlist,
    role_for,
)
from app.presence.watchlist import (
    match as watch_match,
)

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


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


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


def normalise(
    row: dict,
    *,
    kind: str,
    entries: Watchlist | None = None,
) -> dict | None:
    """One aircraft, or None when there is nothing to draw.

    ``t`` is the aircraft type — C30J, AS65. ``type`` is the *message* type,
    "adsb_icao", and reading it here would label every mark identically.

    The role is read from the designator for every aircraft (#954), because a
    feed of four hundred identical marks tells a reader who already knows the
    designators by heart exactly as much as one who does not. The watch label
    and the airborne clock are only for aircraft on the operator's list: the
    clock is this process's memory of what it has seen, and keeping it for
    routine traffic would mean remembering four hundred aircraft to print a
    number nobody asked for.
    """
    lat, lon = _number(row.get("lat")), _number(row.get("lon"))
    if lat is None or lon is None:
        return None
    item = {
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
        #: The aggregator's own database flag, carried rather than restated
        #: (#954). Bit 1 is "military" in its scheme, and it is *its* claim
        #: about an airframe, not a reading of anything the aircraft
        #: transmitted. A government or head-of-state transport is flagged this
        #: way too, so a wide-body airliner on the military list is the flag
        #: working, not the layer failing — and the card has to say whose flag
        #: it is or the console is asserting something it never checked.
        "source_flags": _int(row.get("dbFlags")),
        "role": role_for(_text(row.get("t"))),
        "watch": None,
        "airborne_since": None,
    }
    entry = watch_match(item, entries or EMPTY_WATCHLIST)
    if entry is None:
        return item
    item["watch"] = {"label": entry.label, "category": entry.category}
    key = (item["hex"] or item["registration"] or "").upper()
    first_seen = note_airborne(key, alt_ft=item["alt_ft"]) if key else None
    if first_seen is not None:
        item["airborne_since"] = (
            datetime.fromtimestamp(first_seen, UTC).replace(microsecond=0).isoformat()
        )
    return item


def merge(
    military: list[dict],
    distressed: list[dict],
    watched: list[dict] | None = None,
    entries: Watchlist | None = None,
) -> list[dict]:
    """Every list, deduped by transponder address, distress winning.

    A military aircraft squawking 7700 is one aircraft with two reasons to be
    on the map, and the urgent reason is the one worth drawing. A watched
    aircraft that is also in the military list is likewise one aircraft: it
    keeps ``military`` as its kind and carries the watch label as well, since
    the label is what makes it findable and the kind is what it is.

    ``watched`` is applied first so the two lists that describe an aircraft
    more urgently can overwrite it.
    """
    by_hex: dict[str, dict] = {}
    for row in watched or []:
        item = normalise(row, kind="watched", entries=entries)
        if item and item["hex"]:
            by_hex[item["hex"]] = item
    for row in military:
        item = normalise(
            row,
            kind="distress" if is_distressed(row) else "military",
            entries=entries,
        )
        if item and item["hex"]:
            by_hex[item["hex"]] = item
    for row in distressed:
        item = normalise(row, kind="distress", entries=entries)
        if item and item["hex"]:
            by_hex[item["hex"]] = item
    #: Distress first, then anything being watched, then the rest. The order is
    #: what a reader would ask for: the emergency, the aircraft they came to
    #: find, and then the traffic.
    return sorted(
        by_hex.values(),
        key=lambda a: (a["kind"] != "distress", a["watch"] is None, a["hex"]),
    )


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


#: How many identifiers go in one URL. The aggregator accepts a comma-joined
#: list — verified live, three hexes in and three aircraft out — but a URL that
#: grows with the watchlist would eventually be refused for its length rather
#: than its content, and the failure would look like a data problem.
_WATCH_BATCH = 40


def _looks_like_hex(key: str) -> bool:
    """Whether an identifier is a transponder address rather than a tail number.

    Six hexadecimal digits is the ICAO address; anything else on the list is a
    registration. Registrations that happen to be six hex digits do not exist —
    they carry a dash or a letter outside A-F — so the two never collide.
    """
    return len(key) == 6 and all(c in "0123456789ABCDEF" for c in key)


def _fetch_watched(
    client: httpx.Client,
    source: PresenceSource,
    entries: Watchlist,
) -> tuple[list[dict], bool]:
    """The watchlist's own aircraft, asked for by identifier.

    Asked for directly rather than filtered out of the military list, because
    the interesting airframes are not all military: a civil-registered aircraft
    never appears in that list at all and could not otherwise be drawn.

    Returns what was found and whether anything was refused. A refusal here
    must not cost the military list, which is the layer's whole picture.
    """
    if not entries:
        return [], False

    #: Only the named airframes are asked about upstream. A rule — a role, a
    #: callsign prefix — cannot be turned into a query, and does not need to
    #: be: it matches inside the military list this refresh already fetched.
    hexes = sorted(k for k in entries.exact if _looks_like_hex(k))
    regs = sorted(k for k in entries.exact if not _looks_like_hex(k))
    found: list[dict] = []
    degraded = False
    for path, keys in (("hex", hexes), ("reg", regs)):
        for start in range(0, len(keys), _WATCH_BATCH):
            batch = keys[start : start + _WATCH_BATCH]
            if not batch:
                continue
            try:
                payload = _get_json(client, source, f"/v2/{path}/{','.join(batch)}")
                found.extend(payload.get("ac") or [])
            except Exception:
                degraded = True
    return found, degraded


def _fetch(
    client: httpx.Client,
    source: PresenceSource,
    entries: Watchlist | None = None,
) -> dict:
    """The military list, one distress code in rotation, and the watchlist.

    Partial failure is kept partial. A refused squawk check must not discard a
    military list that arrived intact — losing a hundred aircraft because one
    rare-by-design query was rate-limited is a worse answer than a slightly
    incomplete one, and the response says which happened. The watchlist query
    is held to the same rule.
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

    watched, watch_degraded = _fetch_watched(client, source, entries or EMPTY_WATCHLIST)
    degraded = degraded or watch_degraded

    #: Anything not heard from for a long time is dropped from the airborne
    #: ledger here, once per refresh, so a gap of hours is never reported as
    #: one continuous flight.
    forget_stale()

    #: A distressed *military* aircraft needs no extra request: the military
    #: payload already carries squawk and emergency on every row, and `merge`
    #: reads them.
    aircraft = merge(military, distressed, watched, entries or EMPTY_WATCHLIST)
    #: How many airframes are on the list, which is not how many are flying.
    #: The console needs both to say anything useful when the layer draws
    #: nothing: a watchlist nobody configured and a watchlist whose aircraft
    #: are all on the ground look identical on a map, and they are not the
    #: same situation. Entries are keyed by hex *and* registration, so the
    #: distinct labels are counted rather than the keys.
    watching = (entries or EMPTY_WATCHLIST).size
    return {
        "fetched_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "count": len(aircraft),
        "watching": watching,
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

    #: Read every refresh rather than once at import, so an operator editing
    #: the file does not have to restart the console to be watching something
    #: new. The file is small and the read is local; the request that follows
    #: costs orders of magnitude more.
    entries, watchlist_status = resolve_watchlist()

    owned = client is None
    http = client or _new_client()
    try:
        answer = _fetch(http, source, entries)
        #: Said in the answer rather than only in a log, because the reader who
        #: needs to know is looking at a rail row that says "none watched" and
        #: has no way to tell that from "your file could not be read" (#959).
        answer["watchlist_status"] = watchlist_status
    finally:
        if owned:
            http.close()

    #: An empty degraded picture is never cached: pinning "nothing" in place for
    #: the whole window would turn one refused request into half a minute of
    #: blank map.
    if not (answer["degraded"] and answer["count"] == 0):
        _cache["aircraft"] = (now, answer)
    return answer
