"""Real hazard footprint geometry enrichment (issue #205).

Hazard events store points only, so the map drew synthesized circles. The real
shapes are published free by the upstream sources:

* **USGS** — a ShakeMap (when one exists) exposes ``cont_mmi.json``: a
  FeatureCollection of MultiLineString MMI intensity contours, each already
  carrying its own ``color``.
* **GDACS** — every event has a footprint GeoJSON resource holding the real
  Polygon extent (burn scar, flood area, …) alongside a Point marker.

The normalised FeatureCollection is stored under ``payload.footprint_geojson``
(no schema migration; the read-API already serves the whole payload). The
frontend renders it via the existing fill+line layers, falling back to the
synthesized circle when no real geometry is available.

Pure parsing/normalisation is split from the HTTP calls so it can be unit
tested without network. Every fetch returns ``None`` on any error — enrichment
is best-effort and must never break ingestion.
"""

from __future__ import annotations

import json
from typing import Any, Final

import httpx
from shapely.geometry import mapping, shape

USGS_DETAIL_URL: Final[str] = (
    "https://earthquake.usgs.gov/fdsnws/event/1/query?eventid={usgs_id}&format=geojson"
)
GDACS_FOOTPRINT_URL: Final[str] = (
    "https://www.gdacs.org/contentdata/resources/{event_type}/{event_id}/"
    "geojson_{event_id}_{episode}.geojson"
)
EONET_EVENT_URL: Final[str] = "https://eonet.gsfc.nasa.gov/api/v3/events/{eonet_id}"
USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"
#: EONET storms (cyclones) carry no alert level — draw the track in the storm
#: green that matches the wind pin.
_EONET_TRACK_COLOR: Final[str] = "#22c55e"

#: GDACS alert level → footprint colour (mirrors the frontend hazard palette).
_ALERT_COLOR: Final[dict[str, str]] = {
    "green": "#22c55e",
    "orange": "#f97316",
    "red": "#ef4444",
}
_DEFAULT_COLOR: Final[str] = "#f97316"
_POLYGON_FILL_OPACITY: Final[float] = 0.25


#: Serialized size a single event's footprint may occupy (issue #613). The map
#: ships the whole payload in its list response and polls up to 2 000 events, so
#: a 2 MB GDACS flood boundary is paid for on every refresh. 50 kB still holds
#: several thousand vertices — far more than is visible at the zoom levels a
#: world map is used at.
FOOTPRINT_BYTE_BUDGET: Final[int] = 50_000
#: Douglas-Peucker tolerances in degrees, tried in order until the collection
#: fits. 0.005° ≈ 550 m; the last resort ≈ 28 km, which only the very largest
#: admin-boundary footprints ever reach.
_SIMPLIFY_TOLERANCES: Final[tuple[float, ...]] = (0.005, 0.01, 0.02, 0.05, 0.1, 0.25)


# --------------------------------------------------------------------------- #
# Pure parsing / normalisation                                                #
# --------------------------------------------------------------------------- #


def geojson_bytes(fc: dict[str, Any]) -> int:
    """Serialized size of a FeatureCollection, as the API would send it."""
    return len(json.dumps(fc, separators=(",", ":")))


def _keep_multi(simplified: dict[str, Any], original: dict[str, Any]) -> dict[str, Any]:
    """Restore a single-part Multi* geometry that shapely collapsed.

    Simplifying a MultiLineString/MultiPolygon that holds one part hands back
    the bare part. Harmless to draw, but the stored geometry should keep the
    type it arrived with.
    """
    was_multi = str(original.get("type", "")).startswith("Multi")
    if was_multi and not str(simplified.get("type", "")).startswith("Multi"):
        return {"type": original["type"], "coordinates": [simplified["coordinates"]]}
    return simplified


def _simplified(fc: dict[str, Any], tolerance: float) -> dict[str, Any]:
    """Douglas-Peucker every feature, keeping the original when it cannot help.

    A feature that fails to simplify (invalid ring, degenerate geometry) or that
    simplifies away to nothing is kept as-is — an oversized footprint still
    beats a missing one.
    """
    out: list[dict[str, Any]] = []
    for ft in fc.get("features", []):
        geometry = ft.get("geometry")
        try:
            simple = shape(geometry).simplify(tolerance, preserve_topology=True)
            if not simple.is_empty:
                geometry = _keep_multi(json.loads(json.dumps(mapping(simple))), geometry)
        except Exception:  # geometry libraries raise broadly; keep the original shape
            pass
        out.append({**ft, "geometry": geometry})
    return {**fc, "features": out}


def fit_to_budget(
    fc: dict[str, Any] | None, *, budget: int = FOOTPRINT_BYTE_BUDGET
) -> dict[str, Any] | None:
    """Simplify a footprint collection just enough to fit `budget` bytes.

    Anything already under budget is returned untouched, so the ordinary small
    footprint keeps every vertex. Only the outliers — GDACS flood and shake
    boundaries traced along administrative borders, up to 2 MB each — get
    coarsened, and only as far as needed.
    """
    if fc is None or geojson_bytes(fc) <= budget:
        return fc
    best = fc
    for tolerance in _SIMPLIFY_TOLERANCES:
        best = _simplified(fc, tolerance)
        if geojson_bytes(best) <= budget:
            return best
    return _drop_heaviest(best, budget)


def _drop_heaviest(fc: dict[str, Any], budget: int) -> dict[str, Any]:
    """Last resort: shed whole features, heaviest first, until the rest fit.

    Simplification cannot help a GDACS shake band made of thousands of separate
    grid cells — the vertices are already minimal, the part count is the cost.
    The heaviest feature in such a collection is the weakest, widest band; the
    inner bands that carry the actual signal are small and survive. At least one
    feature is always kept.
    """
    features = sorted(fc.get("features", []), key=lambda f: -len(json.dumps(f.get("geometry"))))
    while len(features) > 1 and geojson_bytes({**fc, "features": features}) > budget:
        features = features[1:]
    return {**fc, "features": features}


def usgs_mmi_contour_url(detail: dict[str, Any]) -> str | None:
    """Dig the ShakeMap MMI contour URL out of a USGS detail GeoJSON document.

    Returns ``None`` when the event has no ShakeMap product (common for small
    quakes) or the document is malformed.
    """
    if not isinstance(detail, dict):
        return None
    products = (detail.get("properties") or {}).get("products") or {}
    shakemaps = products.get("shakemap")
    if not isinstance(shakemaps, list) or not shakemaps:
        return None
    contents = (shakemaps[0] or {}).get("contents") or {}
    entry = contents.get("download/cont_mmi.json")
    if not isinstance(entry, dict):
        return None
    url = entry.get("url")
    return url if isinstance(url, str) and url.startswith("http") else None


def normalize_usgs_footprint(fc: dict[str, Any]) -> dict[str, Any] | None:
    """Normalise a USGS ``cont_mmi.json`` FeatureCollection for the map.

    Keeps the contour lines as-is, guaranteeing each feature's properties carry
    a ``color`` (USGS already sets one) and ``fillOpacity`` (0 — contours are
    lines, not fills). Returns ``None`` when there is nothing usable.
    """
    features = _features(fc)
    if not features:
        return None
    out: list[dict[str, Any]] = []
    for ft in features:
        geom = ft.get("geometry") if isinstance(ft, dict) else None
        if not isinstance(geom, dict) or "coordinates" not in geom:
            continue
        props = ft.get("properties") or {}
        color = props.get("color") if isinstance(props.get("color"), str) else _DEFAULT_COLOR
        out.append(
            {
                "type": "Feature",
                "properties": {"color": color, "fillOpacity": 0},
                "geometry": geom,
            }
        )
    if not out:
        return None
    return fit_to_budget({"type": "FeatureCollection", "features": out})


def gdacs_footprint_url(event_type: str, event_id: str, episode: int = 1) -> str:
    """Build the GDACS footprint GeoJSON resource URL."""
    return GDACS_FOOTPRINT_URL.format(event_type=event_type, event_id=event_id, episode=episode)


#: GDACS footprint geometries we keep. Areas (wind zones, burn scars, flood
#: extent) are filled; line geometries (cyclone track) are stroked only.
_GDACS_AREA_TYPES: Final[tuple[str, ...]] = ("Polygon", "MultiPolygon")
_GDACS_LINE_TYPES: Final[tuple[str, ...]] = ("LineString", "MultiLineString")


def normalize_gdacs_footprint(fc: dict[str, Any], color: str) -> dict[str, Any] | None:
    """Keep the real area + track geometry from a GDACS footprint FeatureCollection.

    Areas (Polygon/MultiPolygon — wind zones, burn scars, flood extent) are
    filled; the cyclone track (LineString/MultiLineString) is stroked only. The
    Point marker GDACS ships is dropped (the map already pins the event).
    Returns ``None`` when no usable geometry exists.
    """
    features = _features(fc)
    if not features:
        return None
    out: list[dict[str, Any]] = []
    for ft in features:
        geom = ft.get("geometry") if isinstance(ft, dict) else None
        if not isinstance(geom, dict) or "coordinates" not in geom:
            continue
        geom_type = geom.get("type")
        if geom_type in _GDACS_AREA_TYPES:
            fill_opacity = _POLYGON_FILL_OPACITY
        elif geom_type in _GDACS_LINE_TYPES:
            fill_opacity = 0
        else:
            continue
        out.append(
            {
                "type": "Feature",
                "properties": {"color": color, "fillOpacity": fill_opacity},
                "geometry": geom,
            }
        )
    if not out:
        return None
    return fit_to_budget({"type": "FeatureCollection", "features": out})


def alert_color(alert_level: str | None) -> str:
    """Map a GDACS alert level to its footprint colour."""
    if not alert_level:
        return _DEFAULT_COLOR
    return _ALERT_COLOR.get(alert_level.lower(), _DEFAULT_COLOR)


def _features(fc: Any) -> list[Any]:
    if not isinstance(fc, dict):
        return []
    features = fc.get("features")
    return features if isinstance(features, list) else []


# --------------------------------------------------------------------------- #
# HTTP (best-effort — never raises)                                           #
# --------------------------------------------------------------------------- #


def _get_json(client: httpx.Client, url: str) -> dict[str, Any] | None:
    try:
        response = client.get(url)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def fetch_usgs_footprint(usgs_id: str, *, client: httpx.Client) -> dict[str, Any] | None:
    """Fetch + normalise the ShakeMap MMI contours for a USGS event."""
    detail = _get_json(client, USGS_DETAIL_URL.format(usgs_id=usgs_id))
    if detail is None:
        return None
    url = usgs_mmi_contour_url(detail)
    if url is None:
        return None
    fc = _get_json(client, url)
    if fc is None:
        return None
    return normalize_usgs_footprint(fc)


def fetch_gdacs_footprint(
    event_type: str,
    event_id: str,
    *,
    color: str,
    episode: int = 1,
    client: httpx.Client,
) -> dict[str, Any] | None:
    """Fetch + normalise the GDACS footprint polygon for an event."""
    fc = _get_json(client, gdacs_footprint_url(event_type, event_id, episode))
    if fc is None:
        return None
    return normalize_gdacs_footprint(fc, color)


def eonet_track_geojson(detail: dict[str, Any], color: str) -> dict[str, Any] | None:
    """Build a storm-track LineString from an EONET event's geometry list.

    EONET ships a severe-storm event as an ordered list of dated Point
    observations (the path). Stitch their coordinates into a single LineString
    so the map can draw the typhoon track. Returns ``None`` when there are
    fewer than two usable points.
    """
    if not isinstance(detail, dict):
        return None
    geometry = detail.get("geometry")
    if not isinstance(geometry, list):
        return None
    coords: list[list[float]] = []
    for g in geometry:
        if not isinstance(g, dict) or g.get("type") != "Point":
            continue
        c = g.get("coordinates")
        if isinstance(c, list) and len(c) >= 2:
            try:
                coords.append([float(c[0]), float(c[1])])
            except (TypeError, ValueError):
                continue
    if len(coords) < 2:
        return None
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"color": color, "fillOpacity": 0},
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        ],
    }


def fetch_eonet_footprint(
    eonet_id: str, *, color: str, client: httpx.Client
) -> dict[str, Any] | None:
    """Fetch an EONET event detail and build its storm-track LineString."""
    detail = _get_json(client, EONET_EVENT_URL.format(eonet_id=eonet_id))
    if detail is None:
        return None
    return eonet_track_geojson(detail, color)


def footprint_for_event(
    source: str, payload: dict[str, Any], *, client: httpx.Client
) -> dict[str, Any] | None:
    """Dispatch to the right upstream for a hazard event's real footprint.

    Returns a normalised FeatureCollection or ``None`` (no geometry / error).
    """
    if source == "usgs-quake":
        usgs_id = payload.get("usgs_id")
        if isinstance(usgs_id, str) and usgs_id:
            return fetch_usgs_footprint(usgs_id, client=client)
        return None
    if source == "gdacs":
        color = alert_color(payload.get("alert_level"))
        # Prefer the direct geometry URL from the geteventlist API — it has the
        # correct episode baked in and returns the full footprint (wind zones +
        # cyclone track). Fall back to the contentdata resource for older rows.
        geometry_url = payload.get("geometry_url")
        if isinstance(geometry_url, str) and geometry_url.startswith("http"):
            fc = _get_json(client, geometry_url)
            return normalize_gdacs_footprint(fc, color) if fc is not None else None
        event_type = payload.get("event_type")
        event_id = payload.get("gdacs_event_id")
        if isinstance(event_type, str) and isinstance(event_id, str) and event_id:
            return fetch_gdacs_footprint(event_type, event_id, color=color, client=client)
        return None
    if source == "eonet":
        eonet_id = payload.get("eonet_id")
        if isinstance(eonet_id, str) and eonet_id:
            return fetch_eonet_footprint(eonet_id, color=_EONET_TRACK_COLOR, client=client)
        return None
    return None
