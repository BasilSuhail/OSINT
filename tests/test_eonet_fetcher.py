"""Tests for `app.sources.eonet_fetcher`."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.models import Category
from app.sources.eonet_fetcher import (
    EONET_FEED_URL,
    EonetFetcher,
    _severity_for,
    feature_to_event,
    parse_eonet_body,
)


def _wildfire_record(
    *,
    event_id: str = "EONET_20558",
    title: str = "Test Wildfire, Idaho",
    acres: float | None = 1000.0,
    lat: float = 42.81,
    lon: float = -114.77,
    date: str = "2026-06-17T13:57:00Z",
    closed: str | None = None,
) -> dict:
    geometry = {
        "type": "Point",
        "coordinates": [lon, lat],
        "date": date,
    }
    if acres is not None:
        geometry["magnitudeValue"] = acres
        geometry["magnitudeUnit"] = "acres"
    return {
        "id": event_id,
        "title": title,
        "description": None,
        "link": f"https://eonet.gsfc.nasa.gov/api/v3/events/{event_id}",
        "closed": closed,
        "categories": [{"id": "wildfires", "title": "Wildfires"}],
        "sources": [{"id": "IRWIN", "url": "https://example.gov/incident/abc"}],
        "geometry": [geometry],
    }


def _storm_record(
    *,
    event_id: str = "EONET_99001",
    pressures: list[tuple[str, float, float, float]] | None = None,
) -> dict:
    """Multi-point storm trajectory with hPa magnitudes."""
    if pressures is None:
        pressures = [
            ("2026-06-15T00:00:00Z", 14.0, -50.0, 990.0),
            ("2026-06-16T00:00:00Z", 18.0, -60.0, 960.0),
            ("2026-06-17T00:00:00Z", 22.0, -70.0, 935.0),
        ]
    geometry = [
        {
            "type": "Point",
            "coordinates": [lon, lat],
            "date": date,
            "magnitudeValue": p,
            "magnitudeUnit": "hpa",
        }
        for date, lat, lon, p in pressures
    ]
    return {
        "id": event_id,
        "title": "Test Cyclone",
        "categories": [{"id": "severeStorms", "title": "Severe Storms"}],
        "sources": [{"id": "JTWC", "url": "https://example.mil/storm"}],
        "geometry": geometry,
        "closed": None,
    }


class TestSeverityFor:
    def test_missing_magnitude_neutral(self) -> None:
        assert _severity_for(None, None) == 0.5

    def test_missing_unit_neutral(self) -> None:
        assert _severity_for(1000.0, None) == 0.5

    def test_unknown_unit_neutral(self) -> None:
        assert _severity_for(1.0, "weird") == 0.5

    def test_acres_scales_linearly(self) -> None:
        # 100k acres = 1.0 ceiling
        assert _severity_for(100_000.0, "acres") == pytest.approx(1.0)
        assert _severity_for(50_000.0, "acres") == pytest.approx(0.5)
        assert _severity_for(0.0, "acres") == pytest.approx(0.0)

    def test_hpa_inverts_lower_is_stronger(self) -> None:
        # 900 hpa = strongest = 1.0; 1015 hpa = weakest = 0.0
        assert _severity_for(900.0, "hpa") == pytest.approx(1.0)
        assert _severity_for(1015.0, "hpa") == pytest.approx(0.0)
        # 957.5 = midpoint
        assert _severity_for(957.5, "hpa") == pytest.approx(0.5)

    def test_clamps_above_ceiling(self) -> None:
        assert _severity_for(10_000_000.0, "acres") == pytest.approx(1.0)


class TestFeatureToEvent:
    def test_wildfire_happy_path(self) -> None:
        fetched_at = datetime(2026, 6, 18, 0, 0, tzinfo=UTC)
        ev = feature_to_event(_wildfire_record(), fetched_at=fetched_at)
        assert ev is not None
        assert ev.source == "eonet"
        assert ev.source_event_id == "EONET_20558"
        assert ev.category == Category.HAZARD
        assert ev.occurred_at == datetime(2026, 6, 17, 13, 57, tzinfo=UTC)
        assert ev.lat == pytest.approx(42.81)
        assert ev.lon == pytest.approx(-114.77)
        assert ev.severity == pytest.approx(0.01)  # 1000 / 100k
        assert "wildfires" in ev.keywords
        assert "eonet" in ev.keywords
        assert ev.payload["title"] == "Test Wildfire, Idaho"
        assert ev.payload["categories"] == ["wildfires"]
        assert ev.payload["sources"] == [{"id": "IRWIN", "url": "https://example.gov/incident/abc"}]

    def test_storm_uses_latest_geometry(self) -> None:
        fetched_at = datetime(2026, 6, 18, 0, 0, tzinfo=UTC)
        ev = feature_to_event(_storm_record(), fetched_at=fetched_at)
        assert ev is not None
        # Latest geometry = 2026-06-17, lat 22, lon -70, 935 hpa.
        assert ev.lat == pytest.approx(22.0)
        assert ev.lon == pytest.approx(-70.0)
        assert ev.occurred_at == datetime(2026, 6, 17, 0, 0, tzinfo=UTC)
        # 935 hpa → severity (1015-935)/(1015-900) ≈ 0.696
        assert ev.severity == pytest.approx(0.6956, abs=1e-3)

    def test_missing_id_drops(self) -> None:
        bad = _wildfire_record()
        bad.pop("id")
        ev = feature_to_event(bad, fetched_at=datetime.now(UTC))
        assert ev is None

    def test_missing_geometry_drops(self) -> None:
        bad = _wildfire_record()
        bad["geometry"] = []
        ev = feature_to_event(bad, fetched_at=datetime.now(UTC))
        assert ev is None

    def test_missing_magnitude_neutral_severity(self) -> None:
        ev = feature_to_event(_wildfire_record(acres=None), fetched_at=datetime.now(UTC))
        assert ev is not None
        assert ev.severity == pytest.approx(0.5)


class TestParseEonetBody:
    def test_parses_multi_event(self) -> None:
        body = json.dumps(
            {
                "events": [
                    _wildfire_record(event_id="EONET_1"),
                    _storm_record(event_id="EONET_2"),
                    {"id": "broken"},  # invalid → dropped silently
                ]
            }
        )
        events = parse_eonet_body(body, fetched_at=datetime.now(UTC))
        ids = {e.source_event_id for e in events}
        assert ids == {"EONET_1", "EONET_2"}

    def test_malformed_json_returns_empty(self) -> None:
        assert parse_eonet_body("{not json", fetched_at=datetime.now(UTC)) == []

    def test_no_events_key_returns_empty(self) -> None:
        assert parse_eonet_body("{}", fetched_at=datetime.now(UTC)) == []


@respx.mock
def test_fetcher_round_trip() -> None:
    body = json.dumps({"events": [_wildfire_record()]})
    respx.get(EONET_FEED_URL).mock(return_value=httpx.Response(200, text=body))
    fetcher = EonetFetcher()
    events = fetcher.fetch()
    assert len(events) == 1
    assert events[0].source == "eonet"
    assert events[0].source_event_id == "EONET_20558"


@respx.mock
def test_fetcher_raises_on_5xx() -> None:
    respx.get(EONET_FEED_URL).mock(return_value=httpx.Response(503))
    fetcher = EonetFetcher()
    with pytest.raises(httpx.HTTPStatusError):
        fetcher.fetch()


def test_archive_path_partitions_by_date() -> None:
    fetcher = EonetFetcher()
    path = fetcher.archive_path()
    assert path.startswith("/mnt/data/parquet/eonet/year=")
    assert "/month=" in path
    assert "/day=" in path
