"""Tests for `app.sources.usgs_quake_fetcher`."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.models import Category
from app.sources.usgs_quake_fetcher import (
    USGS_FEED_URL,
    UsgsQuakeFetcher,
    _magnitude_to_severity,
    feature_to_event,
    parse_geojson_body,
)


def _make_feature(
    *,
    event_id: str = "us7000abcd",
    magnitude: float = 6.0,
    time_ms: int = 1_750_000_000_000,
    alert: str | None = None,
    lat: float = 35.0,
    lon: float = 140.0,
    depth: float = 30.5,
    place: str = "Off the east coast of Honshu, Japan",
) -> dict:
    properties = {
        "mag": magnitude,
        "time": time_ms,
        "alert": alert,
        "place": place,
        "tsunami": 0,
        "felt": 12,
    }
    return {
        "id": event_id,
        "type": "Feature",
        "properties": properties,
        "geometry": {"type": "Point", "coordinates": [lon, lat, depth]},
    }


class TestMagnitudeToSeverity:
    def test_m3_floors_at_zero(self) -> None:
        assert _magnitude_to_severity(3.0) == 0.0

    def test_m10_caps_at_one(self) -> None:
        assert _magnitude_to_severity(10.0) == 1.0

    def test_midpoint(self) -> None:
        assert _magnitude_to_severity(6.5) == pytest.approx(0.5)

    def test_below_three_clamps_to_zero(self) -> None:
        assert _magnitude_to_severity(1.0) == 0.0

    def test_above_ten_clamps_to_one(self) -> None:
        assert _magnitude_to_severity(15.0) == 1.0


class TestFeatureToEvent:
    def test_basic_feature_emits_event(self) -> None:
        feature = _make_feature(magnitude=6.0)
        event = feature_to_event(feature, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.source == "usgs-quake"
        assert event.category == Category.HAZARD
        assert event.source_event_id == "us7000abcd"
        assert event.severity == pytest.approx((6.0 - 3.0) / 7.0)
        assert event.lat == pytest.approx(35.0)
        assert event.lon == pytest.approx(140.0)
        assert event.payload["depth_km"] == pytest.approx(30.5)
        assert "earthquake" in event.keywords

    def test_pager_alert_overrides_magnitude(self) -> None:
        feature = _make_feature(magnitude=4.5, alert="red")
        event = feature_to_event(feature, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.severity == 1.0
        assert event.payload["alert"] == "red"

    def test_unknown_alert_falls_back_to_magnitude(self) -> None:
        feature = _make_feature(magnitude=7.0, alert="purple")
        event = feature_to_event(feature, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.severity == pytest.approx((7.0 - 3.0) / 7.0)

    def test_missing_required_field_skipped(self) -> None:
        feature = _make_feature()
        feature["properties"]["mag"] = None
        assert feature_to_event(feature, fetched_at=datetime.now(UTC)) is None

    def test_missing_event_id_skipped(self) -> None:
        feature = _make_feature()
        feature["id"] = None
        assert feature_to_event(feature, fetched_at=datetime.now(UTC)) is None

    def test_bad_time_skipped(self) -> None:
        feature = _make_feature()
        feature["properties"]["time"] = "not-a-timestamp"
        assert feature_to_event(feature, fetched_at=datetime.now(UTC)) is None

    def test_missing_coordinates_keeps_event_with_none_latlon(self) -> None:
        feature = _make_feature()
        feature["geometry"] = {"type": "Point", "coordinates": []}
        event = feature_to_event(feature, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.lat is None
        assert event.lon is None

    def test_country_is_none_for_now(self) -> None:
        event = feature_to_event(_make_feature(), fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.country is None  # reverse-geocoding is a future PR


class TestParseGeojsonBody:
    def test_empty_body_returns_empty(self) -> None:
        assert parse_geojson_body("", fetched_at=datetime.now(UTC)) == []

    def test_invalid_json_returns_empty(self) -> None:
        assert parse_geojson_body("not json", fetched_at=datetime.now(UTC)) == []

    def test_multiple_features_parsed(self) -> None:
        body = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    _make_feature(event_id="A", magnitude=6.0),
                    _make_feature(event_id="B", magnitude=8.0),
                    {"id": "bad", "properties": {}},  # malformed → dropped
                ],
            }
        )
        events = parse_geojson_body(body, fetched_at=datetime.now(UTC))
        ids = [e.source_event_id for e in events]
        assert ids == ["A", "B"]


class TestFetcherContract:
    def test_name_and_queue(self) -> None:
        f = UsgsQuakeFetcher()
        assert f.name == "usgs-quake"
        assert f.queue == "slow"

    def test_archive_path_partitioned(self) -> None:
        path = UsgsQuakeFetcher().archive_path()
        assert path.startswith("/mnt/data/parquet/usgs-quake/year=")
        assert "month=" in path
        assert "day=" in path

    def test_rejects_non_positive_timeout(self) -> None:
        with pytest.raises(ValueError):
            UsgsQuakeFetcher(timeout_seconds=0)


class TestFetcherHttp:
    @respx.mock
    def test_fetch_calls_feed_and_returns_events(self) -> None:
        body = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [_make_feature(event_id="X", magnitude=7.0)],
            }
        )
        respx.get(USGS_FEED_URL).mock(return_value=httpx.Response(200, text=body))
        events = UsgsQuakeFetcher().fetch()
        assert len(events) == 1
        assert events[0].source_event_id == "X"

    @respx.mock
    def test_fetch_raises_on_http_error(self) -> None:
        respx.get(USGS_FEED_URL).mock(return_value=httpx.Response(500))
        with pytest.raises(httpx.HTTPStatusError):
            UsgsQuakeFetcher().fetch()
