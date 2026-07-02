"""Tests for `app.sources.gdacs_fetcher`."""

from __future__ import annotations

from datetime import UTC, datetime
from xml.etree import ElementTree as ET

import httpx
import pytest
import respx

from app.models import Category
from app.sources.gdacs_fetcher import (
    GDACS_API_EVENT_TYPES,
    GdacsFetcher,
    _alert_to_severity,
    feature_to_event_api,
    iso3_to_iso2,
    item_to_event,
    parse_eventlist_json,
    parse_rss_body,
)


def _build_rss(
    *,
    event_id: str = "1000001",
    event_type: str = "EQ",
    alert_level: str = "Orange",
    iso3: str = "JPN",
    point: str = "35.0 140.0",
    severity_raw: str = "6.5",
    severity_value: str = "6.5",
    pub_date: str = "Wed, 18 Jun 2026 12:00:00 GMT",
) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:gdacs="http://www.gdacs.org" xmlns:georss="http://www.georss.org/georss">
  <channel>
    <title>GDACS</title>
    <item>
      <title>Earthquake in Japan</title>
      <link>https://www.gdacs.org/example/{event_id}</link>
      <pubDate>{pub_date}</pubDate>
      <gdacs:eventid>{event_id}</gdacs:eventid>
      <gdacs:eventtype>{event_type}</gdacs:eventtype>
      <gdacs:alertlevel>{alert_level}</gdacs:alertlevel>
      <gdacs:country>Japan</gdacs:country>
      <gdacs:iso3>{iso3}</gdacs:iso3>
      <gdacs:severity unit="M" value="{severity_value}">{severity_raw}</gdacs:severity>
      <gdacs:fromdate>2026-06-18T12:00:00</gdacs:fromdate>
      <gdacs:todate>2026-06-18T13:00:00</gdacs:todate>
      <georss:point>{point}</georss:point>
    </item>
  </channel>
</rss>
"""


class TestIso3ToIso2:
    def test_known_codes(self) -> None:
        assert iso3_to_iso2("JPN") == "JP"
        assert iso3_to_iso2("USA") == "US"
        assert iso3_to_iso2("GBR") == "GB"
        assert iso3_to_iso2("RUS") == "RU"
        assert iso3_to_iso2("UKR") == "UA"
        assert iso3_to_iso2("DEU") == "DE"
        assert iso3_to_iso2("GUM") == "GU"
        assert iso3_to_iso2("MNP") == "MP"
        assert iso3_to_iso2("NCL") == "NC"

    def test_lowercase_accepted(self) -> None:
        assert iso3_to_iso2("jpn") == "JP"

    def test_unknown_returns_none(self) -> None:
        assert iso3_to_iso2("XXX") is None

    def test_empty_returns_none(self) -> None:
        assert iso3_to_iso2("") is None
        assert iso3_to_iso2(None) is None


class TestAlertToSeverity:
    def test_levels(self) -> None:
        assert _alert_to_severity("Green") == 0.2
        assert _alert_to_severity("orange") == 0.6
        assert _alert_to_severity("RED") == 1.0

    def test_unknown_returns_none(self) -> None:
        assert _alert_to_severity("Purple") is None
        assert _alert_to_severity(None) is None


class TestItemToEvent:
    def test_basic_item_emits_event(self) -> None:
        body = _build_rss()
        root = ET.fromstring(body)
        item = root.find(".//item")
        assert item is not None
        event = item_to_event(item, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.source == "gdacs"
        assert event.category == Category.HAZARD
        assert event.source_event_id == "EQ:1000001"
        assert event.severity == 0.6  # orange
        assert event.country == "JP"
        assert event.lat == 35.0
        assert event.lon == 140.0
        assert event.payload["iso3"] == "JPN"
        assert event.payload["country_name"] == "Japan"
        assert event.payload["severity_raw"] == "6.5"
        assert "gdacs" in event.keywords
        assert "eq" in event.keywords

    def test_earthquake_magnitude_and_depth_parsed(self) -> None:
        # Real GDACS quake severity: value attr = magnitude, text carries depth.
        body = _build_rss(
            severity_value="6.9",
            severity_raw="Magnitude 6.9M, Depth:50.9km",
        )
        root = ET.fromstring(body)
        item = root.find(".//item")
        assert item is not None
        event = item_to_event(item, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.payload["magnitude"] == 6.9
        assert event.payload["depth_km"] == 50.9

    def test_non_earthquake_has_no_magnitude(self) -> None:
        # A tropical cyclone's severity value is wind speed, not magnitude.
        body = _build_rss(event_type="TC", severity_value="120", severity_raw="120 km/h")
        root = ET.fromstring(body)
        item = root.find(".//item")
        assert item is not None
        event = item_to_event(item, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.payload["magnitude"] is None
        assert event.payload["depth_km"] is None

    def test_unknown_alert_skips_item(self) -> None:
        body = _build_rss(alert_level="Purple")
        root = ET.fromstring(body)
        item = root.find(".//item")
        assert item is not None
        assert item_to_event(item, fetched_at=datetime.now(UTC)) is None

    def test_missing_event_id_skips(self) -> None:
        body = _build_rss(event_id="")
        root = ET.fromstring(body)
        item = root.find(".//item")
        assert item is not None
        assert item_to_event(item, fetched_at=datetime.now(UTC)) is None

    def test_unmapped_iso3_keeps_event_with_country_none(self) -> None:
        body = _build_rss(iso3="XXX")
        root = ET.fromstring(body)
        item = root.find(".//item")
        assert item is not None
        event = item_to_event(item, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.country is None
        assert event.payload["iso3"] == "XXX"

    def test_invalid_point_keeps_event_with_none_latlon(self) -> None:
        body = _build_rss(point="not coords")
        root = ET.fromstring(body)
        item = root.find(".//item")
        assert item is not None
        event = item_to_event(item, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.lat is None
        assert event.lon is None


class TestParseRssBody:
    def test_empty_body_returns_empty(self) -> None:
        assert parse_rss_body("", fetched_at=datetime.now(UTC)) == []

    def test_invalid_xml_returns_empty(self) -> None:
        assert parse_rss_body("not xml", fetched_at=datetime.now(UTC)) == []

    def test_multiple_items_parsed(self) -> None:
        body = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:gdacs="http://www.gdacs.org" xmlns:georss="http://www.georss.org/georss">
  <channel>
    <title>GDACS</title>
    <item>
      <gdacs:eventid>1000001</gdacs:eventid>
      <gdacs:eventtype>EQ</gdacs:eventtype>
      <gdacs:alertlevel>Orange</gdacs:alertlevel>
      <gdacs:iso3>JPN</gdacs:iso3>
      <georss:point>35.0 140.0</georss:point>
    </item>
    <item>
      <gdacs:eventid>2000002</gdacs:eventid>
      <gdacs:eventtype>TC</gdacs:eventtype>
      <gdacs:alertlevel>Red</gdacs:alertlevel>
      <gdacs:iso3>PHL</gdacs:iso3>
      <georss:point>14.0 121.0</georss:point>
    </item>
  </channel>
</rss>"""
        events = parse_rss_body(body, fetched_at=datetime.now(UTC))
        assert len(events) == 2
        ids = [e.source_event_id for e in events]
        assert "EQ:1000001" in ids
        assert "TC:2000002" in ids


class TestFetcherContract:
    def test_name_and_queue(self) -> None:
        f = GdacsFetcher()
        assert f.name == "gdacs"
        assert f.queue == "slow"

    def test_archive_path(self) -> None:
        path = GdacsFetcher().archive_path()
        assert path.startswith("/mnt/data/parquet/gdacs/year=")
        assert "month=" in path

    def test_rejects_non_positive_timeout(self) -> None:
        with pytest.raises(ValueError):
            GdacsFetcher(timeout_seconds=0)


def _api_feature(
    event_type: str, event_id: int, *, alert: str = "Green", iscurrent: str = "true"
) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [137.5, 34.0]},
        "properties": {
            "eventtype": event_type,
            "eventid": event_id,
            "episodeid": 18,
            "eventname": f"{event_type}-{event_id}",
            "alertlevel": alert,
            "country": "Japan",
            "iso3": "JPN",
            "affectedcountries": [
                {"iso2": "JP", "iso3": "JPN", "countryname": "Japan"},
                {"iso2": "GU", "iso3": "GUM", "countryname": "Guam"},
            ],
            "fromdate": "2026-06-26T16:06:49",
            "todate": "2026-06-27T00:00:00",
            "datemodified": "2026-06-27T01:02:03",
            "iscurrent": iscurrent,
            "istemporary": "false",
            "severitydata": {"severity": 6.0, "severitytext": "Magnitude 6M, Depth:30km"},
            "url": {
                "geometry": "https://www.gdacs.org/geom.geojson",
                "report": "https://www.gdacs.org/report.aspx",
            },
        },
    }


def _api_body(*features: dict) -> str:
    import json

    return json.dumps({"type": "FeatureCollection", "features": list(features)})


class TestApiParser:
    def test_feature_to_event_api_basic(self) -> None:
        at = datetime(2026, 6, 26, tzinfo=UTC)
        ev = feature_to_event_api(_api_feature("VO", 1000141, alert="Orange"), fetched_at=at)
        assert ev is not None
        assert ev.source == "gdacs"
        assert ev.source_event_id == "VO:1000141"
        assert ev.category is Category.HAZARD
        assert ev.lat == 34.0 and ev.lon == 137.5
        assert ev.payload["event_type"] == "VO"
        assert ev.payload["geometry_url"] == "https://www.gdacs.org/geom.geojson"
        assert ev.payload["link"] == "https://www.gdacs.org/report.aspx"
        assert ev.payload["is_current"] is True
        assert ev.payload["is_temporary"] is False
        assert ev.payload["affected_countries"] == [
            {"iso2": "JP", "iso3": "JPN", "countryname": "Japan"},
            {"iso2": "GU", "iso3": "GUM", "countryname": "Guam"},
        ]

    def test_active_event_stamped_at_fetch_time(self) -> None:
        # GDACS only lists active events, but a long-running hazard keeps an old
        # onset (fromdate). It must read as current so it stays in the dashboard's
        # live window; the real onset is preserved in the payload (#252).
        at = datetime(2026, 7, 2, tzinfo=UTC)
        feature = _api_feature("WF", 42)
        feature["properties"]["fromdate"] = "2026-06-16T00:00:00"
        ev = feature_to_event_api(feature, fetched_at=at)
        assert ev is not None
        assert ev.occurred_at == at
        assert ev.payload["from_date"] == "2026-06-16T00:00:00"

    def test_feature_to_event_api_parses_eq_magnitude_depth(self) -> None:
        at = datetime(2026, 6, 26, tzinfo=UTC)
        ev = feature_to_event_api(_api_feature("EQ", 555), fetched_at=at)
        assert ev is not None
        assert ev.payload["magnitude"] == 6.0
        assert ev.payload["depth_km"] == 30.0

    def test_feature_to_event_api_drops_invalid(self) -> None:
        at = datetime(2026, 6, 26, tzinfo=UTC)
        assert feature_to_event_api({"properties": {}}, fetched_at=at) is None
        # unknown alert level → severity None → dropped
        assert feature_to_event_api(_api_feature("TC", 1, alert="Bogus"), fetched_at=at) is None
        # GDACS geteventlist includes historical rows; closed rows must not enter the live feed.
        assert feature_to_event_api(_api_feature("TC", 2, iscurrent="false"), fetched_at=at) is None

    def test_parse_eventlist_json(self) -> None:
        body = _api_body(_api_feature("TC", 1), _api_feature("VO", 2))
        events = parse_eventlist_json(body, fetched_at=datetime(2026, 6, 26, tzinfo=UTC))
        assert {e.source_event_id for e in events} == {"TC:1", "VO:2"}

    def test_parse_eventlist_json_bad_input(self) -> None:
        at = datetime(2026, 6, 26, tzinfo=UTC)
        assert parse_eventlist_json("not json", fetched_at=at) == []
        assert parse_eventlist_json("{}", fetched_at=at) == []


class TestFetcherHttp:
    @respx.mock
    def test_fetch_queries_each_type_and_dedups(self) -> None:
        # One respx route matches every per-type API call; return a TC + VO each.
        body = _api_body(_api_feature("TC", 1), _api_feature("VO", 2))
        respx.get(url__startswith="https://www.gdacs.org/gdacsapi/api/events/geteventlist").mock(
            return_value=httpx.Response(200, text=body)
        )
        events = GdacsFetcher().fetch()
        # Same features returned for every type → deduped by source_event_id.
        assert {e.source_event_id for e in events} == {"TC:1", "VO:2"}

    @respx.mock
    def test_one_type_failing_does_not_lose_others(self) -> None:
        # All calls 503 → best-effort fetch returns empty, never raises.
        respx.get(url__startswith="https://www.gdacs.org/gdacsapi/api/events/geteventlist").mock(
            return_value=httpx.Response(503)
        )
        assert GdacsFetcher().fetch() == []

    def test_event_types_cover_volcano_and_cyclone(self) -> None:
        assert "VO" in GDACS_API_EVENT_TYPES
        assert "TC" in GDACS_API_EVENT_TYPES
