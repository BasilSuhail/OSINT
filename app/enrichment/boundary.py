"""Fine-grained point→country lookup for the place screen.

``app.enrichment.country`` resolves points against Natural Earth 110 m and says
in its own docstring that a point within ~10 km of a border may land on the
wrong side. That is the right trade for ingest, which attributes millions of
points into month-scale country buckets and would rather not hold finer
polygons in every worker.

It is the wrong trade for a screen whose first line names a country. So the
50 m file lives here, behind its own lazy loader: nothing pays for it until
somebody right-clicks the map, and the ingest path never imports this module.

The distance to the border comes back with the answer. A polygon can only
support so much confidence, and a screen that never says which side of a line
it is guessing at is a screen that is sometimes quietly wrong.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

_DATA_PATH = Path(__file__).parent / "data" / "admin0_countries_50m.geojson"

#: Under this, the screen says so. Chosen against the 50 m dataset's own
#: resolution: finer than this and the polygon is the source of the error.
NEAR_BORDER_KM = 5.0

_KM_PER_DEGREE = 111.32


@lru_cache(maxsize=1)
def _index() -> tuple[STRtree, list[str], list[BaseGeometry]]:
    """Build the tree on first use, not at import.

    Ingest imports the sibling module in every worker; making this one eager
    would add two megabytes of polygons to processes that never look at them.
    """
    with _DATA_PATH.open() as handle:
        document = json.load(handle)

    geometries: list[BaseGeometry] = []
    isos: list[str] = []
    for feature in document.get("features", []):
        properties = feature.get("properties") or {}
        iso = properties.get("ISO_A2")
        if not isinstance(iso, str) or len(iso) != 2 or iso.startswith("-"):
            iso = properties.get("ISO_A2_EH")
            if not isinstance(iso, str) or len(iso) != 2 or iso.startswith("-"):
                continue
        geometry = feature.get("geometry")
        if not geometry:
            continue
        try:
            geom = shape(geometry)
        except Exception:  # a malformed polygon is skipped, never guessed at
            continue
        if geom.is_empty:
            continue
        geometries.append(geom)
        isos.append(iso.upper())

    if not geometries:
        raise RuntimeError(f"no country polygons loaded from {_DATA_PATH}")
    tree = STRtree(geometries)
    return tree, isos, list(tree.geometries)


def _valid(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    return -90 <= lat <= 90 and -180 <= lon <= 180


@lru_cache(maxsize=4096)
def precise_country(lat: float, lon: float) -> str | None:
    """ISO alpha-2 for the country containing the point, or None over water."""
    if not _valid(lat, lon):
        return None
    tree, isos, geoms = _index()
    point = Point(lon, lat)
    for index in tree.query(point):
        if geoms[int(index)].contains(point):
            return isos[int(index)]
    return None


@lru_cache(maxsize=4096)
def border_distance_km(lat: float, lon: float, iso: str) -> float | None:
    """Distance from the point to that country's own edge, in kilometres.

    Degrees convert with a cosine correction on longitude, which is accurate
    enough for a threshold measured in kilometres and avoids reprojecting a
    whole country to answer one question. Returns None when the country is not
    in the dataset — an unknown code produces no distance rather than a zero
    that would read as "right on the border".
    """
    if not _valid(lat, lon) or not iso:
        return None
    _tree, isos, geoms = _index()
    point = Point(lon, lat)
    wanted = iso.upper()
    scale = _KM_PER_DEGREE * max(math.cos(math.radians(lat)), 0.1)
    best: float | None = None
    for index, code in enumerate(isos):
        if code != wanted:
            continue
        km = geoms[index].boundary.distance(point) * scale
        if best is None or km < best:
            best = km
    return best
