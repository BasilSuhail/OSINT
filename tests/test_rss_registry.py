"""Tests for the JSON-driven RSS registry (issue #158)."""

from __future__ import annotations

import json
from pathlib import Path

from app.sources.rss_registry import (
    build_rss_fetchers,
    content_owner_map,
    feed_cadence_map,
    load_feed_configs,
    outlet_country_map,
)

_FEEDS_PATH = Path("app/sources/rss_feeds.json")


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


def test_every_feed_declares_an_owner() -> None:
    """WS-C step 2 (#355): each feed names who controls its editorial output."""
    for entry in json.loads(_FEEDS_PATH.read_text(encoding="utf-8")):
        owner = entry.get("owner")
        assert owner, f"{entry['source']} has no owner"
        assert owner == owner.lower() and " " not in owner


def test_content_owner_map_covers_every_feed() -> None:
    owners = content_owner_map()
    assert set(owners.keys()) == {c.source for c in load_feed_configs()}


def test_content_owner_map_collapses_shared_owners() -> None:
    """Two BBC feeds are one owner; RT + TASS are both Russian-state-controlled."""
    owners = content_owner_map()
    assert owners["rss-bbc-world"] == owners["rss-bbc-uk"]
    assert owners["rss-rt-news"] == owners["rss-tass-en"]
    assert owners["rss-dawn"] != owners["rss-guardian-world"]


def test_content_owner_map_syndication_wins_over_feed_owner() -> None:
    """The Yahoo-hosted feed carries Reuters wire — the words are Reuters'."""
    owners = content_owner_map()
    assert owners["rss-reuters-world"] == "reuters"


def test_every_feed_declares_an_origin_country() -> None:
    """WS-B step 1 (#368): each feed names where its editorial voice sits."""
    for entry in json.loads(_FEEDS_PATH.read_text(encoding="utf-8")):
        country = entry.get("country")
        assert country, f"{entry['source']} has no origin country"
        assert len(country) == 2 and country == country.upper()


def test_outlet_country_map_covers_every_feed() -> None:
    countries = outlet_country_map()
    assert set(countries.keys()) == {c.source for c in load_feed_configs()}


def test_outlet_country_map_spot_checks() -> None:
    countries = outlet_country_map()
    assert countries["rss-bbc-world"] == "GB"
    assert countries["rss-rt-news"] == countries["rss-tass-en"] == "RU"
    assert countries["rss-kyiv-independent"] == "UA"
    # Syndicated feed: origin follows the content owner (Reuters), not the host.
    assert countries["rss-reuters-world"] == "GB"


def test_roster_widened_beyond_anglosphere() -> None:
    """WS-B step 1 (#368): at least 12 new voices, at least 10 new origin countries."""
    configs = load_feed_configs()
    assert len(configs) >= 37
    origins = set(outlet_country_map().values())
    for iso2 in ("ZA", "KE", "EG", "MX", "BR", "KR", "ID", "VN", "TR"):
        assert iso2 in origins, f"no outlet voice from {iso2}"
    assert len(origins) >= 25


def test_build_rss_fetchers_returns_one_instance_per_slug() -> None:
    fetchers = build_rss_fetchers()
    #: Parked feeds (#490) get no fetcher — compare against the enabled set.
    configs = load_feed_configs(enabled_only=True)
    assert set(fetchers.keys()) == {c.source for c in configs}
    # Every fetcher's config matches its slug.
    for slug, fetcher in fetchers.items():
        assert fetcher.config.source == slug
        assert fetcher.name == slug


def test_parked_feeds_leave_schedule_but_keep_metadata() -> None:
    """#490: nhk-world and rt-news are parked (dead URL / network-blocked).

    They must vanish from the fetch/schedule paths but keep resolving in the
    metadata maps so their historical events rows stay labeled.
    """
    parked = {"rss-nhk-world", "rss-rt-news"}
    assert parked.isdisjoint(feed_cadence_map())
    assert parked.isdisjoint(build_rss_fetchers())
    assert parked.isdisjoint({c.source for c in load_feed_configs(enabled_only=True)})
    # default listing + maps keep them
    assert parked <= {c.source for c in load_feed_configs()}
    assert parked <= set(content_owner_map())
    assert parked <= set(outlet_country_map())


def test_revived_feeds_use_live_urls() -> None:
    """#490: kyiv-independent and tribune-pk moved to verified-live URLs."""
    urls = {c.source: c.url for c in load_feed_configs(enabled_only=True)}
    assert urls["rss-kyiv-independent"] == "https://kyivindependent.com/feed/rss/"
    assert urls["rss-tribune-pk"] == "https://tribune.com.pk/feed/latest"
