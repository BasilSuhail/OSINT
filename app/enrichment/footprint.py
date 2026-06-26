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

from typing import Any, Final

import httpx

USGS_DETAIL_URL: Final[str] = (
    "https://earthquake.usgs.gov/fdsnws/event/1/query?eventid={usgs_id}&format=geojson"
)
GDACS_FOOTPRINT_URL: Final[str] = (
    "https://www.gdacs.org/contentdata/resources/{event_type}/{event_id}/"
    "geojson_{event_id}_{episode}.geojson"
)
USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"

#: GDACS alert level → footprint colour (mirrors the frontend hazard palette).
_ALERT_COLOR: Final[dict[str, str]] = {
    "green": "#22c55e",
    "orange": "#f97316",
    "red": "#ef4444",
}
_DEFAULT_COLOR: Final[str] = "#f97316"
_POLYGON_FILL_OPACITY: Final[float] = 0.25


# --------------------------------------------------------------------------- #
# Pure parsing / normalisation                                                #
# --------------------------------------------------------------------------- #


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
    return {"type": "FeatureCollection", "features": out}


def gdacs_footprint_url(event_type: str, event_id: str, episode: int = 1) -> str:
    """Build the GDACS footprint GeoJSON resource URL."""
    return GDACS_FOOTPRINT_URL.format(
        event_type=event_type, event_id=event_id, episode=episode
    )


def normalize_gdacs_footprint(
    fc: dict[str, Any], color: str
) -> dict[str, Any] | None:
    """Keep only the real area geometry (Polygon/MultiPolygon) from a GDACS
    footprint FeatureCollection, tagging each with the alert colour + fill.

    The Point marker GDACS ships alongside the polygon is dropped (the map
    already pins the event). Returns ``None`` when no area geometry exists.
    """
    features = _features(fc)
    if not features:
        return None
    out: list[dict[str, Any]] = []
    for ft in features:
        geom = ft.get("geometry") if isinstance(ft, dict) else None
        if not isinstance(geom, dict):
            continue
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        if "coordinates" not in geom:
            continue
        out.append(
            {
                "type": "Feature",
                "properties": {"color": color, "fillOpacity": _POLYGON_FILL_OPACITY},
                "geometry": geom,
            }
        )
    if not out:
        return None
    return {"type": "FeatureCollection", "features": out}


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


def fetch_usgs_footprint(
    usgs_id: str, *, client: httpx.Client
) -> dict[str, Any] | None:
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
        event_type = payload.get("event_type")
        event_id = payload.get("gdacs_event_id")
        if isinstance(event_type, str) and isinstance(event_id, str) and event_id:
            color = alert_color(payload.get("alert_level"))
            return fetch_gdacs_footprint(
                event_type, event_id, color=color, client=client
            )
        return None
    return None
