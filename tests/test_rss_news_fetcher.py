"""Tests for `app.sources.rss_news_fetcher`."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.models import Category
from app.sources.rss_news_fetcher import (
    NEWS_DEFAULT_SEVERITY,
    NEWS_KEYWORD_SEVERITY,
    BBCUKNewsFetcher,
    BBCWorldNewsFetcher,
    DawnNewsFetcher,
    GeoEnglishNewsFetcher,
    GuardianWorldNewsFetcher,
    ReutersWorldNewsFetcher,
    RssFeedConfig,
    RssNewsFetcher,
    _hash_event_id,
    _severity_for,
    _strip_html,
    entry_to_event,
    parse_rss_body,
)

FAKE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Demo</title>
  <link>https://example.com</link>
  <description>Demo</description>
  <item>
    <title>Knife attack reported in Edinburgh</title>
    <link>https://example.com/news/edinburgh-knife</link>
    <description><![CDATA[<p>Police were called to a scene in Edinburgh today.</p>]]></description>
    <guid>guid-001</guid>
    <pubDate>Mon, 21 Jun 2026 10:15:00 GMT</pubDate>
  </item>
  <item>
    <title>Markets in cautious mood ahead of central bank meet</title>
    <link>https://example.com/news/markets</link>
    <description>Investors awaited the central bank decision.</description>
    <guid>guid-002</guid>
    <pubDate>Mon, 21 Jun 2026 09:00:00 GMT</pubDate>
  </item>
  <item>
    <title></title>
    <link>https://example.com/oops</link>
    <description></description>
    <pubDate>not-a-date</pubDate>
  </item>
</channel>
</rss>"""


CFG = RssFeedConfig(
    source="rss-test",
    url="https://example.com/rss",
    default_country="GB",
    pretty_name="Test Feed",
)


class TestHelpers:
    def test_strip_html(self) -> None:
        assert _strip_html("<p>hello <b>world</b></p>") == "hello world"

    def test_strip_html_empty(self) -> None:
        assert _strip_html("") == ""

    def test_hash_event_id_deterministic(self) -> None:
        a = _hash_event_id("rss-bbc-uk", "https://example.com/a", "title")
        b = _hash_event_id("rss-bbc-uk", "https://example.com/a", "title")
        assert a == b
        c = _hash_event_id("rss-bbc-uk", "https://example.com/b", "title")
        assert a != c

    def test_severity_default(self) -> None:
        assert (
            _severity_for("local fundraiser opens", "people raise money") == NEWS_DEFAULT_SEVERITY
        )

    def test_severity_keyword_attack(self) -> None:
        assert _severity_for("Police called after attack in town", "") == NEWS_KEYWORD_SEVERITY

    def test_severity_keyword_fire_in_summary(self) -> None:
        assert (
            _severity_for("Latest update", "A large fire broke out overnight")
            == NEWS_KEYWORD_SEVERITY
        )


class TestEntryToEvent:
    def test_basic_entry(self) -> None:
        entry = {
            "title": "Knife attack reported in Edinburgh",
            "link": "https://example.com/news/edinburgh-knife",
            "summary": "Police were called to Edinburgh today.",
            "id": "guid-001",
            "published_parsed": (2026, 6, 21, 10, 15, 0, 0, 0, 0),
        }
        event = entry_to_event(entry, config=CFG, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.source == "rss-test"
        assert event.source_event_id == "guid-001"
        assert event.category == Category.NEWS
        assert event.severity == NEWS_KEYWORD_SEVERITY  # 'attack' keyword
        assert event.country == "GB"
        assert event.occurred_at == datetime(2026, 6, 21, 10, 15, 0, tzinfo=UTC)
        assert event.payload["title"] == "Knife attack reported in Edinburgh"
        assert event.payload["source_url"] == "https://example.com/news/edinburgh-knife"
        assert event.payload["feed_name"] == "Test Feed"

    def test_no_guid_falls_back_to_hash(self) -> None:
        entry = {
            "title": "Headline",
            "link": "https://example.com/x",
            "summary": "Body",
            "published_parsed": (2026, 6, 21, 0, 0, 0, 0, 0, 0),
        }
        event = entry_to_event(entry, config=CFG, fetched_at=datetime.now(UTC))
        assert event is not None
        assert len(event.source_event_id) == 64  # sha256 hex

    def test_empty_title_skipped(self) -> None:
        entry = {"title": "", "link": "https://example.com", "summary": "body"}
        event = entry_to_event(entry, config=CFG, fetched_at=datetime.now(UTC))
        assert event is None

    def test_no_published_uses_fetched_at(self) -> None:
        fetched_at = datetime(2026, 6, 21, 12, 0, 0, tzinfo=UTC)
        entry = {"title": "T", "link": "u", "summary": "s"}
        event = entry_to_event(entry, config=CFG, fetched_at=fetched_at)
        assert event is not None
        assert event.occurred_at == fetched_at

    def test_default_country_attached(self) -> None:
        entry = {"title": "Hello", "link": "u", "summary": "s"}
        event = entry_to_event(entry, config=CFG, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.country == "GB"

    def test_summary_truncated_at_500(self) -> None:
        entry = {
            "title": "T",
            "link": "u",
            "summary": "a" * 800,
        }
        event = entry_to_event(entry, config=CFG, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.payload["summary"] is not None
        assert len(event.payload["summary"]) == 500


class TestParseRssBody:
    def test_parses_multi_item_feed(self) -> None:
        events = parse_rss_body(FAKE_FEED, config=CFG, fetched_at=datetime.now(UTC))
        # 3rd item has empty title → skipped
        assert len(events) == 2
        assert events[0].payload["title"] == "Knife attack reported in Edinburgh"
        assert events[0].severity == NEWS_KEYWORD_SEVERITY

    def test_empty_body(self) -> None:
        assert parse_rss_body("", config=CFG, fetched_at=datetime.now(UTC)) == []

    def test_garbage_body(self) -> None:
        assert parse_rss_body("not xml", config=CFG, fetched_at=datetime.now(UTC)) == []


class TestFetcherSubclasses:
    @pytest.mark.parametrize(
        "cls,expected_country",
        [
            (BBCWorldNewsFetcher, None),
            (BBCUKNewsFetcher, "GB"),
            (ReutersWorldNewsFetcher, None),
            (DawnNewsFetcher, "PK"),
            (GuardianWorldNewsFetcher, None),
            (GeoEnglishNewsFetcher, "PK"),
        ],
    )
    def test_subclass_config(self, cls: type[RssNewsFetcher], expected_country: str | None) -> None:
        f = cls()
        assert f.name == f.config.source
        assert f.queue == "slow"
        assert f.config.default_country == expected_country

    def test_rejects_non_positive_timeout(self) -> None:
        with pytest.raises(ValueError):
            BBCWorldNewsFetcher(timeout_seconds=0)

    def test_archive_path(self) -> None:
        path = BBCWorldNewsFetcher().archive_path()
        assert path.startswith("/mnt/data/parquet/rss-bbc-world/year=")


class TestFetcherHttp:
    @respx.mock
    def test_fetch_round_trip(self) -> None:
        respx.get("https://feeds.bbci.co.uk/news/uk/rss.xml").mock(
            return_value=httpx.Response(200, text=FAKE_FEED)
        )
        events = BBCUKNewsFetcher().fetch()
        assert len(events) == 2
        assert events[0].source == "rss-bbc-uk"
        assert events[0].country == "GB"

    @respx.mock
    def test_5xx_raises(self) -> None:
        respx.get("https://feeds.bbci.co.uk/news/world/rss.xml").mock(
            return_value=httpx.Response(503)
        )
        with pytest.raises(httpx.HTTPStatusError):
            BBCWorldNewsFetcher().fetch()
