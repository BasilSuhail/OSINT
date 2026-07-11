"""Country-code helpers derived from the bundled Natural Earth dataset."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).parent / "data" / "admin0_countries.geojson"


def _normalize_name(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(value.strip().casefold().replace("&", "and").split())


@lru_cache(maxsize=1)
def _features() -> list[dict[str, Any]]:
    document = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    features = document.get("features", [])
    return [feature for feature in features if isinstance(feature, dict)]


@lru_cache(maxsize=1)
def _iso3_to_iso2_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for feature in _features():
        props = feature.get("properties") or {}
        iso2 = props.get("ISO_A2")
        iso3 = props.get("ISO_A3")
        if (
            isinstance(iso2, str)
            and isinstance(iso3, str)
            and len(iso2) == 2
            and len(iso3) == 3
            and not iso2.startswith("-")
            and not iso3.startswith("-")
        ):
            out[iso3.upper()] = iso2.upper()
    return out


@lru_cache(maxsize=1)
def _country_name_to_iso2_map() -> dict[str, str]:
    out: dict[str, str] = {}
    name_fields = (
        "ADMIN",
        "NAME",
        "NAME_LONG",
        "NAME_EN",
        "NAME_SORT",
        "FORMAL_EN",
        "SOVEREIGNT",
        "GEOUNIT",
    )
    for feature in _features():
        props = feature.get("properties") or {}
        iso2 = props.get("ISO_A2")
        if not isinstance(iso2, str) or len(iso2) != 2 or iso2.startswith("-"):
            continue
        for field in name_fields:
            normalized = _normalize_name(props.get(field))
            if normalized:
                out.setdefault(normalized, iso2.upper())
    return out


@lru_cache(maxsize=1)
def _country_centroids() -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for feature in _features():
        props = feature.get("properties") or {}
        iso2 = props.get("ISO_A2")
        lon = props.get("LABEL_X")
        lat = props.get("LABEL_Y")
        if (
            isinstance(iso2, str)
            and len(iso2) == 2
            and not iso2.startswith("-")
            and isinstance(lat, int | float)
            and isinstance(lon, int | float)
        ):
            out[iso2.upper()] = (float(lat), float(lon))
    return out


def iso3_to_iso2(iso3: str | None) -> str | None:
    if not iso3:
        return None
    return _iso3_to_iso2_map().get(iso3.strip().upper())


def country_name_to_iso2(name: str | None) -> str | None:
    normalized = _normalize_name(name)
    if not normalized:
        return None
    return _country_name_to_iso2_map().get(normalized)


@lru_cache(maxsize=1)
def _iso2_to_name_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for feature in _features():
        props = feature.get("properties") or {}
        # Natural Earth sets ISO_A2 = "-99" for France, Norway and friends;
        # ISO_A2_EH carries the real code in those rows.
        iso2 = props.get("ISO_A2")
        if not isinstance(iso2, str) or len(iso2) != 2 or iso2.startswith("-"):
            iso2 = props.get("ISO_A2_EH")
        if not isinstance(iso2, str) or len(iso2) != 2 or iso2.startswith("-"):
            continue
        name = props.get("NAME_EN") or props.get("NAME") or props.get("ADMIN")
        if isinstance(name, str) and name:
            out.setdefault(iso2.upper(), name)
    return out


def iso2_to_name(iso2: str | None) -> str | None:
    """ISO2 → English country name (the briefing renders codes as words, #401)."""
    if not iso2 or len(iso2) != 2:
        return None
    return _iso2_to_name_map().get(iso2.upper())


def country_centroid(country: str | None) -> tuple[float, float] | None:
    if not country:
        return None
    return _country_centroids().get(country.strip().upper())
