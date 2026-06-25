"""Tests for the news_scope classifier in rss_news_fetcher (#166)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.sources.rss_news_fetcher import RssFeedConfig, entry_to_event

FETCHED_AT = datetime(2026, 6, 23, 12, 0, 0, tzinfo=UTC)


def _entry(title: str, summary: str = "") -> dict:
    return {
        "title": title,
        "summary": summary,
        "link": "https://example.com/story",
        "id": title,
    }


PK_FEED = RssFeedConfig(
    source="rss-dawn",
    url="https://www.dawn.com/feed",
    default_country="PK",
    pretty_name="Dawn",
)

WORLD_FEED = RssFeedConfig(
    source="rss-bbc-world",
    url="https://feeds.bbci.co.uk/news/world/rss.xml",
    default_country=None,
    pretty_name="BBC World",
)


def test_pk_feed_pk_city_is_local() -> None:
    ev = entry_to_event(
        _entry("Karachi blast wounds five"),
        config=PK_FEED,
        fetched_at=FETCHED_AT,
    )
    assert ev is not None
    assert ev.payload["news_scope"] == "local"


def test_pk_feed_us_city_is_world() -> None:
    ev = entry_to_event(
        _entry("Trump speech in New York rattles markets"),
        config=PK_FEED,
        fetched_at=FETCHED_AT,
    )
    assert ev is not None
    assert ev.payload["news_scope"] == "world"


def test_pk_feed_no_city_match_is_unknown() -> None:
    ev = entry_to_event(
        _entry("Taylor Swift's Opalite makes headlines"),
        config=PK_FEED,
        fetched_at=FETCHED_AT,
    )
    assert ev is not None
    assert ev.payload["news_scope"] == "unknown"


def test_world_feed_any_city_match_is_local() -> None:
    ev = entry_to_event(
        _entry("Tokyo exchange opens flat after Wall Street rally"),
        config=WORLD_FEED,
        fetched_at=FETCHED_AT,
    )
    assert ev is not None
    assert ev.payload["news_scope"] == "local"


def test_world_feed_no_city_match_is_unknown() -> None:
    ev = entry_to_event(
        _entry("Generic morning news headline"),
        config=WORLD_FEED,
        fetched_at=FETCHED_AT,
    )
    assert ev is not None
    assert ev.payload["news_scope"] == "unknown"


def test_pk_feed_no_city_match_has_no_country() -> None:
    """Unknown-scope news on a national feed must NOT inherit the feed country.

    Geo / Dawn republish world news (Oscars, foreign quakes). Falling back to
    ``default_country`` tagged those rows ``country='PK'`` and polluted the
    Pakistan country panel. Without a city match the row stays country-less.
    """
    ev = entry_to_event(
        _entry("Jacob Elordi, Jenna Ortega score major Oscars honour"),
        config=PK_FEED,
        fetched_at=FETCHED_AT,
    )
    assert ev is not None
    assert ev.payload["news_scope"] == "unknown"
    assert ev.country is None


def test_pk_feed_pk_city_keeps_country() -> None:
    """Local-scope news (city in the feed country) still attributes to it."""
    ev = entry_to_event(
        _entry("Karachi blast wounds five"),
        config=PK_FEED,
        fetched_at=FETCHED_AT,
    )
    assert ev is not None
    assert ev.payload["news_scope"] == "local"
    assert ev.country == "PK"


def test_pk_feed_foreign_city_uses_real_country() -> None:
    """World-scope news attributes to the city's real country, not the feed."""
    ev = entry_to_event(
        _entry("Trump speech in New York rattles markets"),
        config=PK_FEED,
        fetched_at=FETCHED_AT,
    )
    assert ev is not None
    assert ev.payload["news_scope"] == "world"
    assert ev.country == "US"
