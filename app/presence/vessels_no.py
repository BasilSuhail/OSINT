"""A second sea area: Norwegian coastal AIS (#954).

The first vessel feed covers one sea. This one covers another, and the two
together are still a coastline rather than an ocean — that limit does not go
away by adding sources, it only moves.

Unlike the first feed this one is closed by default: it wants an account and
an OAuth client, which is why it is off unless credentials are configured.
Absent credentials are not a fault and never mark the answer degraded — the
layer is simply not asking, which is a different thing from asking and being
refused.

**The response shape here is written from the operator's documentation and has
not been seen.** Credentials could not be issued while this was written, so
every field is read defensively, alternates are accepted, and a row missing a
position is dropped rather than guessed at. What has been verified live is the
plumbing either side of it: the token endpoint answers a malformed request
with 400 rather than a connection error, and the data endpoint answers an
unauthenticated request with 401. Both are the right answers from the right
hosts. The rest wants one live run with a real client id, which is recorded
on the issue.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

#: Where a token comes from, and what to ask it for.
TOKEN_URL = "https://id.barentswatch.no/connect/token"
TOKEN_SCOPE = "ais"

CLIENT_ID_ENV = "BARENTSWATCH_CLIENT_ID"
CLIENT_SECRET_ENV = "BARENTSWATCH_CLIENT_SECRET"

#: Tokens last an hour; this is refreshed a few minutes early so a refresh
#: never lands in the gap between "still valid" and "just expired".
_TOKEN_EARLY_S = 300

_token: tuple[str, float] | None = None


def clear_token() -> None:
    """Forget the held token. Tests need this; expiry does it for free."""
    global _token
    _token = None


def credentials() -> tuple[str, str] | None:
    """The configured client, or None when this feed is not switched on."""
    client_id = (os.environ.get(CLIENT_ID_ENV) or "").strip()
    client_secret = (os.environ.get(CLIENT_SECRET_ENV) or "").strip()
    if not client_id or not client_secret:
        return None
    return client_id, client_secret


def _fetch_token(client: httpx.Client, client_id: str, client_secret: str) -> str:
    global _token
    now = time.monotonic()
    if _token is not None and _token[1] > now:
        return _token[0]

    response = client.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": TOKEN_SCOPE,
        },
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("no access_token in the token response")
    #: A response with no expiry is treated as the shortest sensible life
    #: rather than as forever: a token believed past its death is a request
    #: refused for a reason nobody can see.
    expires_in = payload.get("expires_in")
    lifetime = float(expires_in) if isinstance(expires_in, (int, float)) else 600.0
    _token = (token, now + max(60.0, lifetime - _TOKEN_EARLY_S))
    return token


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _first(row: dict, *names: str) -> Any:
    """The first field present under any of its documented spellings."""
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def to_feature(row: dict) -> dict | None:
    """One row, reshaped into the geojson feature the vessel layer already reads.

    Reshaped rather than parsed twice: the rest of the layer — the categories,
    the join, the spoofing tests, the age cut — is source-agnostic, and it stays
    that way by making every source look like the first one on the way in.
    """
    if not isinstance(row, dict):
        return None
    lat = _number(_first(row, "latitude", "lat"))
    lon = _number(_first(row, "longitude", "lon"))
    if lat is None or lon is None:
        return None
    mmsi = _first(row, "mmsi")
    if isinstance(mmsi, str) and mmsi.strip().isdigit():
        mmsi = int(mmsi.strip())
    if not isinstance(mmsi, int):
        return None

    msgtime = _first(row, "msgtime", "msgTime", "timestamp")
    reported_ms: float | None = None
    if isinstance(msgtime, str):
        try:
            from datetime import datetime

            reported_ms = datetime.fromisoformat(msgtime.replace("Z", "+00:00")).timestamp() * 1000
        except ValueError:
            reported_ms = None
    elif isinstance(msgtime, (int, float)):
        reported_ms = float(msgtime)

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "mmsi": mmsi,
            "sog": _number(_first(row, "speedOverGround", "sog")),
            "cog": _number(_first(row, "courseOverGround", "cog")),
            "heading": _number(_first(row, "trueHeading", "heading")),
            "navStat": _first(row, "navigationalStatus", "navStat"),
            "timestampExternal": reported_ms,
        },
    }


def to_static(row: dict) -> dict | None:
    """The name and type off the same row.

    This feed sends one row per vessel where the first sends two messages, so
    the static half is unpacked here and handed to the same join. A row with
    nothing but a position still produces an entry: absent stays absent, and
    the vessel is drawn unnamed.
    """
    if not isinstance(row, dict):
        return None
    mmsi = _first(row, "mmsi")
    if isinstance(mmsi, str) and mmsi.strip().isdigit():
        mmsi = int(mmsi.strip())
    if not isinstance(mmsi, int):
        return None
    ship_type = _first(row, "shipType", "shipTypeCode")
    return {
        "mmsi": mmsi,
        "name": _first(row, "name", "shipName"),
        "callSign": _first(row, "callSign", "callsign"),
        "imo": _first(row, "imoNumber", "imo"),
        "shipType": ship_type if isinstance(ship_type, int) else None,
        "destination": _first(row, "destination"),
    }


def fetch(client: httpx.Client, endpoint: str, path: str) -> tuple[list[dict], list[dict]]:
    """Positions and static rows for this sea area, or nothing at all.

    Raises on refusal, like the other feed's fetch, so the caller decides what
    a failure costs. Returning empty on error here would make a refused request
    indistinguishable from an empty sea.
    """
    creds = credentials()
    if creds is None:
        return [], []
    token = _fetch_token(client, *creds)
    response = client.get(f"{endpoint}{path}", headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    payload = response.json()
    rows = payload if isinstance(payload, list) else payload.get("features") or []

    features: list[dict] = []
    statics: list[dict] = []
    for row in rows:
        #: The documented shape is a flat row. A geojson feature is accepted
        #: too, because this has not been seen against the real service and a
        #: wrapper is the likeliest way the documentation is wrong.
        if isinstance(row, dict) and row.get("type") == "Feature":
            props = row.get("properties") or {}
            geometry = row.get("geometry") or {}
            coordinates = geometry.get("coordinates") or []
            if len(coordinates) >= 2:
                props = {**props, "longitude": coordinates[0], "latitude": coordinates[1]}
            row = props
        feature = to_feature(row)
        if feature is None:
            continue
        features.append(feature)
        static = to_static(row)
        if static is not None:
            statics.append(static)
    return features, statics
