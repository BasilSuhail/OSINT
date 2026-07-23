"""Tests for real hazard footprint geometry enrichment (issue #205).

Pure parsing/normalisation only — no network. The HTTP wrappers are thin and
exercised against monkeypatched clients where they add logic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db_models import EventRow
from app.enrichment.footprint import (
    alert_color,
    eonet_track_geojson,
    fetch_usgs_footprint,
    footprint_for_event,
    gdacs_footprint_url,
    normalize_gdacs_footprint,
    normalize_usgs_footprint,
    usgs_mmi_contour_url,
)

_SQUARE = [[0, 0], [1, 0], [1, 1], [0, 0]]


def _polygon(props: dict | None = None) -> dict:
    return {"geometry": {"type": "Polygon", "coordinates": [_SQUARE]}, "properties": props or {}}


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


def test_normalize_gdacs_keeps_cyclone_track_lines() -> None:
    # GDACS cyclone footprint = wind-zone polygons (filled) + track LineString.
    fc = {
        "features": [
            {"geometry": {"type": "Point", "coordinates": [1, 2]}, "properties": {}},
            _polygon(),
            {"geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "properties": {}},
        ],
    }
    out = normalize_gdacs_footprint(fc, "#22c55e")
    assert out is not None
    geoms = {f["geometry"]["type"]: f["properties"]["fillOpacity"] for f in out["features"]}
    assert geoms["Polygon"] == 0.25  # area filled
    assert geoms["LineString"] == 0  # track stroked only
    assert "Point" not in geoms


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
    line = {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]]]}
    mmi = {"features": [{"geometry": line, "properties": {"color": "#fff"}}]}
    detail = _usgs_detail(
        {"download/cont_mmi.json": {"url": "https://earthquake.usgs.gov/x/cont_mmi.json"}}
    )
    client = _FakeClient({"fdsnws/event": detail, "cont_mmi.json": mmi})
    out = fetch_usgs_footprint("us123", client=client)  # type: ignore[arg-type]
    assert out is not None
    assert out["features"][0]["geometry"]["type"] == "MultiLineString"


def test_fetch_usgs_footprint_none_without_shakemap() -> None:
    client = _FakeClient({"fdsnws/event": {"properties": {"products": {}}}})
    assert fetch_usgs_footprint("us123", client=client) is None  # type: ignore[arg-type]


def test_footprint_for_event_dispatch_gdacs() -> None:
    poly = {"features": [_polygon()]}
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


def test_eonet_track_geojson_builds_linestring() -> None:
    detail = {
        "geometry": [
            {"type": "Point", "coordinates": [140.0, 13.7], "date": "2026-06-20"},
            {"type": "Point", "coordinates": [137.5, 20.1], "date": "2026-06-23"},
            {"type": "Point", "coordinates": [133.2, 31.6], "date": "2026-06-26"},
        ]
    }
    out = eonet_track_geojson(detail, "#22c55e")
    assert out is not None
    feat = out["features"][0]
    assert feat["geometry"]["type"] == "LineString"
    assert len(feat["geometry"]["coordinates"]) == 3
    assert feat["properties"]["color"] == "#22c55e"


def test_eonet_track_geojson_none_when_single_point() -> None:
    assert (
        eonet_track_geojson({"geometry": [{"type": "Point", "coordinates": [1, 2]}]}, "#fff")
        is None
    )
    assert eonet_track_geojson({}, "#fff") is None


def test_footprint_for_event_dispatch_eonet() -> None:
    track = {
        "geometry": [
            {"type": "Point", "coordinates": [1, 2]},
            {"type": "Point", "coordinates": [3, 4]},
        ]
    }
    client = _FakeClient({"eonet.gsfc.nasa.gov/api/v3/events/EONET_20606": track})
    out = footprint_for_event("eonet", {"eonet_id": "EONET_20606"}, client=client)  # type: ignore[arg-type]
    assert out is not None
    assert out["features"][0]["geometry"]["type"] == "LineString"


def test_footprint_for_event_gdacs_prefers_geometry_url() -> None:
    poly = {"features": [_polygon()]}
    client = _FakeClient({"gdacs.org/geom.geojson": poly})
    out = footprint_for_event(
        "gdacs",
        {
            "event_type": "VO",
            "gdacs_event_id": "1000141",
            "alert_level": "Orange",
            "geometry_url": "https://www.gdacs.org/geom.geojson",
        },
        client=client,  # type: ignore[arg-type]
    )
    assert out is not None
    assert out["features"][0]["properties"]["color"] == "#f97316"


# --------------------------------------------------------------------------- #
# Backlog scan (issue #604)                                                    #
# --------------------------------------------------------------------------- #


def _hazard_row(source: str, source_event_id: str, *, minutes_ago: int, payload: dict) -> EventRow:
    return EventRow(
        source=source,
        source_event_id=source_event_id,
        occurred_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        fetched_at=datetime.now(UTC),
        category="hazard",
        severity=0.6,
        keywords=[],
        payload=payload,
    )


def _scope(session):
    """A session_scope stand-in that hands back the test's session."""
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        yield session
        session.flush()

    return _cm


def _run_body(monkeypatch, session, *, limit: int, fetched: dict[str, dict | None]):
    from app import tasks

    monkeypatch.setattr(tasks, "session_scope", _scope(session))
    asked: list[str] = []

    def _fake_footprint_for_event(source, payload, *, client):
        key = payload.get("usgs_id") or payload.get("gdacs_event_id") or ""
        asked.append(key)
        return fetched.get(key)

    monkeypatch.setattr("app.enrichment.footprint.footprint_for_event", _fake_footprint_for_event)
    result = tasks._enrich_footprints_body(limit=limit, client=object())  # type: ignore[arg-type]
    return asked, result


def test_scan_skips_rows_that_already_have_geometry(monkeypatch, db_session) -> None:
    # The old query took the newest N hazard rows outright, so already-enriched
    # rows burned the budget and the backlog behind them never drained (#604).
    db_session.add(
        _hazard_row(
            "gdacs",
            "WF:1",
            minutes_ago=1,
            payload={"gdacs_event_id": "1", "footprint_geojson": {"features": [_polygon()]}},
        )
    )
    db_session.add(_hazard_row("gdacs", "DR:2", minutes_ago=5, payload={"gdacs_event_id": "2"}))
    db_session.flush()

    asked, result = _run_body(
        monkeypatch, db_session, limit=1, fetched={"2": {"features": [_polygon()]}}
    )

    assert asked == ["2"]
    assert result["enriched"] == 1


def test_a_footprintless_row_is_not_re_asked_every_run(monkeypatch, db_session) -> None:
    # Most quakes never get a ShakeMap. Without a cooldown they are re-asked on
    # every run and, being the newest rows, starve droughts/floods behind them.
    db_session.add(_hazard_row("usgs-quake", "q1", minutes_ago=1, payload={"usgs_id": "q1"}))
    db_session.add(_hazard_row("gdacs", "DR:2", minutes_ago=5, payload={"gdacs_event_id": "2"}))
    db_session.flush()

    first, _ = _run_body(monkeypatch, db_session, limit=1, fetched={})
    assert first == ["q1"]

    second, _ = _run_body(
        monkeypatch, db_session, limit=1, fetched={"2": {"features": [_polygon()]}}
    )
    assert second == ["2"], "the empty-handed quake was re-asked instead of the drought"


def test_a_stale_cooldown_is_retried(monkeypatch, db_session) -> None:
    stale = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    db_session.add(
        _hazard_row(
            "usgs-quake",
            "q1",
            minutes_ago=1,
            payload={"usgs_id": "q1", "footprint_checked_at": stale},
        )
    )
    db_session.flush()

    asked, _ = _run_body(monkeypatch, db_session, limit=5, fetched={})

    assert asked == ["q1"], "a day-old ShakeMap check was never retried"
