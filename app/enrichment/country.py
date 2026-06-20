"""Lat/lon → ISO 3166-1 alpha-2 country code lookup.

Pure-Python, offline, deterministic. Uses Natural Earth's 110 m Admin-0 dataset
shipped under ``app/enrichment/data/admin0_countries.geojson`` and a Shapely
STRtree for fast point-in-polygon dispatch.

Built once at import time; subsequent calls are O(log N) plus the polygon
intersection cost. The full lookup runs in roughly 30-60 µs on a modern laptop,
so wiring it into every fetcher does not change ingest cadence.

The 110 m dataset is **coarse** — a fire detection within ~10 km of a border may
attribute to the wrong side. For the OSINT thesis composite (country/month
buckets) that error is in the rounding; if border-precision becomes important we
can swap to the 50 m or 10 m dataset by replacing the data file.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

_DATA_PATH = Path(__file__).parent / "data" / "admin0_countries.geojson"


def _load_geometries() -> tuple[STRtree, list[str]]:
    """Build a Shapely STRtree of country polygons and a parallel ISO array."""
    with _DATA_PATH.open() as fh:
        document = json.load(fh)

    geoms = []
    isos: list[str] = []
    for feature in document.get("features", []):
        props = feature.get("properties") or {}
        iso = props.get("ISO_A2")
        if not isinstance(iso, str) or len(iso) != 2 or iso == "-9":
            # Natural Earth marks unassigned features with "-99" / "-9" in
            # ISO_A2; try the post-EH override before giving up.
            iso = props.get("ISO_A2_EH")
            if not isinstance(iso, str) or len(iso) != 2 or iso == "-9":
                continue
        geometry = feature.get("geometry")
        if not geometry:
            continue
        try:
            geom = shape(geometry)
        except Exception:  # bad geometry → skip silently
            continue
        if geom.is_empty:
            continue
        geoms.append(geom)
        isos.append(iso.upper())

    if not geoms:
        raise RuntimeError(f"no country polygons loaded from {_DATA_PATH}")

    tree = STRtree(geoms)
    return tree, isos


_TREE, _ISOS = _load_geometries()
_GEOMS_BY_INDEX = list(_TREE.geometries)


@lru_cache(maxsize=16_384)
def country_for(lat: float, lon: float) -> str | None:
    """Return the ISO 3166-1 alpha-2 code for the country containing ``(lat, lon)``.

    Points in international waters or in the polar caps return ``None``.

    Cache: a 16 k entry LRU keeps the hot set (recent fire detections, recent
    earthquakes) at zero shapely cost. Cache is process-local; the worker pool
    sees its own.
    """
    if lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    point = Point(lon, lat)
    candidates = _TREE.query(point)
    for idx in candidates:
        geom = _GEOMS_BY_INDEX[int(idx)]
        if geom.contains(point):
            return _ISOS[int(idx)]
    return None
