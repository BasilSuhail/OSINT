"""The settlement a right-click is standing in, or near (#932).

The place screen resolves a point to a country and stops. A reader who clicked
one spot is somewhere smaller than that, and until now the screen never named
it.

OpenStreetMap's Nominatim answers the reverse question without a key. Its usage
policy asks for an identifying User-Agent — the place screen's client already
sends one — and no more than one request a second, which a human right-clicking
a map cannot exceed, and which the caller's cache makes rarer still.

## Which name

Nominatim returns several true answers at once: a village inside a county
inside a state. The smallest is the one the reader clicked, so the levels are
read most-specific first.

## How far is too far

Beyond a hundred kilometres, naming a settlement stops being context and starts
reading as an error — "Reykjavík" over the mid-Atlantic. Past the cap this
answers with nothing. The weather block does not depend on this one and still
renders: weather is about the coordinate, not about the town down the road.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx

_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"

#: Past this the settlement is not context for the point any more.
MAX_DISTANCE_KM: int = 100

#: Most specific first: the smallest true answer is the one clicked on.
_SETTLEMENT_KEYS: tuple[str, ...] = (
    "hamlet",
    "village",
    "suburb",
    "town",
    "city",
    "municipality",
)

#: Same order of preference for the line under the name.
_REGION_KEYS: tuple[str, ...] = ("county", "state_district", "state", "region")

_EARTH_RADIUS_KM = 6371.0088


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance. Small enough to keep rather than take a dependency."""
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * asin(sqrt(a))


def read_address(body: dict[str, Any]) -> dict | None:
    """The settlement in a reverse-geocode answer, or None if it names none."""
    address = body.get("address") or {}
    name = next((address[key] for key in _SETTLEMENT_KEYS if address.get(key)), None)
    if not name:
        return None
    region = next((address[key] for key in _REGION_KEYS if address.get(key)), None)
    return {
        "name": name,
        "region": region,
        #: OSM often carries the Wikidata id of the thing it is describing.
        #: When it does, the population is one cheap, long-cached call away;
        #: when it does not, the block is still worth showing without one.
        "qid": (body.get("extratags") or {}).get("wikidata"),
    }


def nearest_place(client: httpx.Client, lat: float, lon: float) -> dict | None:
    """The settlement at this point, with how far it is from it.

    Raises on an upstream error so the caller can degrade the block. Returns
    None when the answer is simply that nobody lives near here — a fact, not a
    failure, and the two must not look the same on the screen.
    """
    response = client.get(
        _REVERSE_URL,
        params={
            "lat": lat,
            "lon": lon,
            "format": "jsonv2",
            #: City level. Finer returns a building, which is not what "where
            #: am I" means, and coarser returns the country we already have.
            "zoom": 10,
            "extratags": 1,
        },
    )
    response.raise_for_status()
    body = response.json()

    found = read_address(body)
    if found is None:
        return None

    try:
        place_lat = float(body["lat"])
        place_lon = float(body["lon"])
    except (KeyError, TypeError, ValueError):
        return None

    away = distance_km(lat, lon, place_lat, place_lon)
    if away > MAX_DISTANCE_KM:
        return None

    return {**found, "distance_km": round(away, 1), "lat": place_lat, "lon": place_lon}
