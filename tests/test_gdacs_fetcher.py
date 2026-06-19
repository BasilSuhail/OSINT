"""Tests for `app.sources.gdacs_fetcher`."""

from __future__ import annotations

from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import httpx
import pytest
import respx

from app.models import Category
from app.sources.gdacs_fetcher import (
    GDACS_FEED_URL,
    GdacsFetcher,
    _alert_to_severity,
    iso3_to_iso2,
    item_to_event,
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
      <gdacs:severity unit="M">{severity_raw}</gdacs:severity>
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
        event = item_to_event(item, fetched_at=datetime.now(timezone.utc))
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

    def test_unknown_alert_skips_item(self) -> None:
        body = _build_rss(alert_level="Purple")
        root = ET.fromstring(body)
        item = root.find(".//item")
        assert item is not None
        assert item_to_event(item, fetched_at=datetime.now(timezone.utc)) is None

    def test_missing_event_id_skips(self) -> None:
        body = _build_rss(event_id="")
        root = ET.fromstring(body)
        item = root.find(".//item")
        assert item is not None
        assert item_to_event(item, fetched_at=datetime.now(timezone.utc)) is None

    def test_unmapped_iso3_keeps_event_with_country_none(self) -> None:
        body = _build_rss(iso3="XXX")
        root = ET.fromstring(body)
        item = root.find(".//item")
        assert item is not None
        event = item_to_event(item, fetched_at=datetime.now(timezone.utc))
        assert event is not None
        assert event.country is None
        assert event.payload["iso3"] == "XXX"

    def test_invalid_point_keeps_event_with_none_latlon(self) -> None:
        body = _build_rss(point="not coords")
        root = ET.fromstring(body)
        item = root.find(".//item")
        assert item is not None
        event = item_to_event(item, fetched_at=datetime.now(timezone.utc))
        assert event is not None
        assert event.lat is None
        assert event.lon is None


class TestParseRssBody:
    def test_empty_body_returns_empty(self) -> None:
        assert parse_rss_body("", fetched_at=datetime.now(timezone.utc)) == []

    def test_invalid_xml_returns_empty(self) -> None:
        assert parse_rss_body("not xml", fetched_at=datetime.now(timezone.utc)) == []

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
        events = parse_rss_body(body, fetched_at=datetime.now(timezone.utc))
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


class TestFetcherHttp:
    @respx.mock
    def test_fetch_returns_events(self) -> None:
        respx.get(GDACS_FEED_URL).mock(
            return_value=httpx.Response(200, text=_build_rss())
        )
        events = GdacsFetcher().fetch()
        assert len(events) == 1
        assert events[0].source_event_id == "EQ:1000001"

    @respx.mock
    def test_http_error_raises(self) -> None:
        respx.get(GDACS_FEED_URL).mock(return_value=httpx.Response(503))
        with pytest.raises(httpx.HTTPStatusError):
            GdacsFetcher().fetch()
