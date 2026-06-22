"""Tests for the JSON-driven RSS registry (issue #158)."""

from __future__ import annotations

from app.sources.rss_registry import (
    build_rss_fetchers,
    feed_cadence_map,
    load_feed_configs,
)


def test_load_feed_configs_returns_at_least_25_feeds() -> None:
    configs = load_feed_configs()
    assert len(configs) >= 25


def test_existing_six_slugs_still_present() -> None:
    """Backward compat: the six pre-registry slugs keep their `source` IDs."""
    configs = {c.source for c in load_feed_configs()}
    for legacy in (
        "rss-bbc-world",
        "rss-bbc-uk",
        "rss-reuters-world",
        "rss-dawn",
        "rss-guardian-world",
        "rss-geo-english",
    ):
        assert legacy in configs


def test_every_feed_has_pretty_name_and_url() -> None:
    for c in load_feed_configs():
        assert c.pretty_name
        assert c.url.startswith(("http://", "https://"))


def test_feed_cadence_map_returns_minutes_per_slug() -> None:
    cadences = feed_cadence_map()
    assert len(cadences) >= 25
    for slug, min_per in cadences.items():
        assert slug.startswith("rss-")
        assert 5 <= min_per <= 24 * 60


def test_build_rss_fetchers_returns_one_instance_per_slug() -> None:
    fetchers = build_rss_fetchers()
    configs = load_feed_configs()
    assert set(fetchers.keys()) == {c.source for c in configs}
    # Every fetcher's config matches its slug.
    for slug, fetcher in fetchers.items():
        assert fetcher.config.source == slug
        assert fetcher.name == slug
