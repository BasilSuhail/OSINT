"""Tests for real hazard footprint geometry enrichment (issue #205).

Pure parsing/normalisation only — no network. The HTTP wrappers are thin and
exercised against monkeypatched clients where they add logic.
"""

from __future__ import annotations

from app.enrichment.footprint import (
    alert_color,
    fetch_usgs_footprint,
    footprint_for_event,
    gdacs_footprint_url,
    normalize_gdacs_footprint,
    normalize_usgs_footprint,
    usgs_mmi_contour_url,
)


class _FakeResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self._payload = payload
        self._status = status

    def raise_for_status(self) -> None:
        if self._status >= 400:
            import httpx

            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> object:
        return self._payload


class _FakeClient:
    """Returns canned JSON keyed by URL substring."""

    def __init__(self, routes: dict[str, object]) -> None:
        self._routes = routes

    def get(self, url: str) -> _FakeResponse:
        for needle, payload in self._routes.items():
            if needle in url:
                return _FakeResponse(payload)
        return _FakeResponse(None, status=404)


# --------------------------------------------------------------------------- #
# USGS                                                                        #
# --------------------------------------------------------------------------- #


def _usgs_detail(contents: dict) -> dict:
    return {"properties": {"products": {"shakemap": [{"contents": contents}]}}}


def test_usgs_mmi_contour_url_extracts_url() -> None:
    detail = _usgs_detail(
        {"download/cont_mmi.json": {"url": "https://earthquake.usgs.gov/x/cont_mmi.json"}}
    )
    assert usgs_mmi_contour_url(detail) == "https://earthquake.usgs.gov/x/cont_mmi.json"


def test_usgs_mmi_contour_url_none_without_shakemap() -> None:
    assert usgs_mmi_contour_url({"properties": {"products": {}}}) is None
    assert usgs_mmi_contour_url({}) is None
    assert usgs_mmi_contour_url({"properties": {"products": {"shakemap": []}}}) is None


def test_usgs_mmi_contour_url_rejects_non_http() -> None:
    detail = _usgs_detail({"download/cont_mmi.json": {"url": "ftp://nope"}})
    assert usgs_mmi_contour_url(detail) is None


def test_normalize_usgs_keeps_contours_with_color_and_zero_fill() -> None:
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"value": 4.5, "color": "#90f2ff"},
                "geometry": {"type": "MultiLineString", "coordinates": [[[1, 2], [3, 4]]]},
            }
        ],
    }
    out = normalize_usgs_footprint(fc)
    assert out is not None
    assert out["type"] == "FeatureCollection"
    assert len(out["features"]) == 1
    props = out["features"][0]["properties"]
    assert props["color"] == "#90f2ff"
    assert props["fillOpacity"] == 0
    assert out["features"][0]["geometry"]["type"] == "MultiLineString"


def test_normalize_usgs_defaults_color_when_missing() -> None:
    fc = {
        "features": [
            {"geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "properties": {}}
        ]
    }
    out = normalize_usgs_footprint(fc)
    assert out is not None
    assert out["features"][0]["properties"]["color"] == "#f97316"


def test_normalize_usgs_none_when_empty() -> None:
    assert normalize_usgs_footprint({"features": []}) is None
    assert normalize_usgs_footprint({}) is None
    assert normalize_usgs_footprint({"features": [{"properties": {}}]}) is None


# --------------------------------------------------------------------------- #
# GDACS                                                                       #
# --------------------------------------------------------------------------- #


def test_gdacs_footprint_url_format() -> None:
    url = gdacs_footprint_url("WF", "1028883")
    assert url == (
        "https://www.gdacs.org/contentdata/resources/WF/1028883/geojson_1028883_1.geojson"
    )
    assert gdacs_footprint_url("FL", "1103888", episode=3).endswith("geojson_1103888_3.geojson")


def test_normalize_gdacs_keeps_only_polygons() -> None:
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"geometry": {"type": "Point", "coordinates": [1, 2]}, "properties": {}},
            {
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                "properties": {"name": "fire"},
            },
        ],
    }
    out = normalize_gdacs_footprint(fc, "#ef4444")
    assert out is not None
    assert len(out["features"]) == 1
    feat = out["features"][0]
    assert feat["geometry"]["type"] == "Polygon"
    assert feat["properties"]["color"] == "#ef4444"
    assert feat["properties"]["fillOpacity"] == 0.25


def test_normalize_gdacs_none_when_point_only() -> None:
    fc = {"features": [{"geometry": {"type": "Point", "coordinates": [1, 2]}, "properties": {}}]}
    assert normalize_gdacs_footprint(fc, "#22c55e") is None
    assert normalize_gdacs_footprint({}, "#22c55e") is None


def test_alert_color_mapping() -> None:
    assert alert_color("Green") == "#22c55e"
    assert alert_color("orange") == "#f97316"
    assert alert_color("RED") == "#ef4444"
    assert alert_color(None) == "#f97316"
    assert alert_color("weird") == "#f97316"


# --------------------------------------------------------------------------- #
# IO wrappers / dispatch (fake client)                                        #
# --------------------------------------------------------------------------- #


def test_fetch_usgs_footprint_two_hop() -> None:
    mmi = {
        "features": [
            {"geometry": {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]]]}, "properties": {"color": "#fff"}}
        ]
    }
    client = _FakeClient(
        {
            "fdsnws/event": _usgs_detail({"download/cont_mmi.json": {"url": "https://earthquake.usgs.gov/x/cont_mmi.json"}}),
            "cont_mmi.json": mmi,
        }
    )
    out = fetch_usgs_footprint("us123", client=client)  # type: ignore[arg-type]
    assert out is not None
    assert out["features"][0]["geometry"]["type"] == "MultiLineString"


def test_fetch_usgs_footprint_none_without_shakemap() -> None:
    client = _FakeClient({"fdsnws/event": {"properties": {"products": {}}}})
    assert fetch_usgs_footprint("us123", client=client) is None  # type: ignore[arg-type]


def test_footprint_for_event_dispatch_gdacs() -> None:
    poly = {
        "features": [
            {"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, "properties": {}}
        ]
    }
    client = _FakeClient({"contentdata/resources/WF": poly})
    out = footprint_for_event(
        "gdacs",
        {"event_type": "WF", "gdacs_event_id": "1028883", "alert_level": "Red"},
        client=client,  # type: ignore[arg-type]
    )
    assert out is not None
    assert out["features"][0]["properties"]["color"] == "#ef4444"


def test_footprint_for_event_unknown_source() -> None:
    client = _FakeClient({})
    assert footprint_for_event("nasa-firms", {}, client=client) is None  # type: ignore[arg-type]
    assert footprint_for_event("usgs-quake", {}, client=client) is None  # type: ignore[arg-type]
