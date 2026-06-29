"""Country-code helpers derived from the bundled Natural Earth dataset."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).parent / "data" / "admin0_countries.geojson"


@lru_cache(maxsize=1)
def _iso3_to_iso2_map() -> dict[str, str]:
    document = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for feature in document.get("features", []):
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


def iso3_to_iso2(iso3: str | None) -> str | None:
    if not iso3:
        return None
    return _iso3_to_iso2_map().get(iso3.strip().upper())
