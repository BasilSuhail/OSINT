"""Tests for the JSON-driven RSS registry (issue #158)."""

from __future__ import annotations

import json
from pathlib import Path

from app.sources.rss_registry import (
    build_rss_fetchers,
    content_owner_map,
    feed_cadence_map,
    feed_enabled_map,
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
    assert all(feed_enabled_map()[source] is False for source in parked)


def test_enabled_map_covers_every_declared_feed() -> None:
    assert set(feed_enabled_map()) == {config.source for config in load_feed_configs()}
    assert feed_enabled_map()["rss-bbc-world"] is True


def test_revived_feeds_use_live_urls() -> None:
    """#490: kyiv-independent and tribune-pk moved to verified-live URLs."""
    urls = {c.source: c.url for c in load_feed_configs(enabled_only=True)}
    assert urls["rss-kyiv-independent"] == "https://kyivindependent.com/feed/rss/"
    assert urls["rss-tribune-pk"] == "https://tribune.com.pk/feed/latest"


def test_desk_country_map_covers_only_country_section_feeds() -> None:
    from app.sources.rss_registry import desk_country_map

    assert desk_country_map() == {
        "rss-bbc-uk": "GB",
        "rss-nation-kenya": "KE",
        "rss-scmp-china": "CN",
        # City and region desks (#805): the URL *is* that place's section, so
        # every story in the feed is about that country by construction.
        "rss-edinburgh-live": "GB",
        "rss-glasgow-live": "GB",
        "rss-men-manchester": "GB",
        "rss-bbc-manchester": "GB",
        "rss-nation-lahore": "PK",
    }


def test_world_desks_declare_no_desk_country() -> None:
    from app.sources.rss_registry import desk_country_map

    desks = desk_country_map()
    for world_feed in (
        "rss-nyt-world",
        "rss-cbc-world",
        "rss-dw-world",
        "rss-straits-times-world",
        "rss-bbc-world",
    ):
        assert world_feed not in desks


def test_every_desk_country_is_a_valid_iso2() -> None:
    from app.sources.rss_registry import desk_country_map

    for source, iso in desk_country_map().items():
        assert len(iso) == 2 and iso.isupper(), f"{source} has a malformed desk_country"


#: The local tier (#805). Ten feeds that report on somewhere in particular,
#: added because 44 national and world desks produced six positioned rows for
#: Edinburgh in a week and no ranking change can find stories the corpus does
#: not hold.
LOCAL_TIER = (
    "rss-edinburgh-live",
    "rss-glasgow-live",
    "rss-stv-news",
    "rss-herald-scotland",
    "rss-scotsman",
    "rss-men-manchester",
    "rss-bbc-manchester",
    "rss-nation-lahore",
    "rss-capital-fm-kenya",
    "rss-standard-kenya",
)


def test_local_tier_is_present_and_fetched() -> None:
    """#805: every local feed is live in the registry, not parked."""
    enabled = {c.source for c in load_feed_configs(enabled_only=True)}
    for slug in LOCAL_TIER:
        assert slug in enabled, f"{slug} missing from the enabled feeds"
        assert slug in feed_cadence_map(), f"{slug} has no fetch cadence"


def test_local_tier_urls_are_the_ones_that_were_measured() -> None:
    """The desk URL is the point. A masthead-wide feed is a different source
    with a different rate and a different local share, so pin what was probed."""
    urls = {c.source: c.url for c in load_feed_configs(enabled_only=True)}
    assert urls["rss-edinburgh-live"] == (
        "https://www.edinburghlive.co.uk/news/edinburgh-news/?service=rss"
    )
    assert urls["rss-glasgow-live"] == (
        "https://www.glasgowlive.co.uk/news/glasgow-news/?service=rss"
    )
    assert urls["rss-men-manchester"] == (
        "https://www.manchestereveningnews.co.uk/news/greater-manchester-news/?service=rss"
    )
    assert urls["rss-nation-lahore"] == "https://www.nation.com.pk/rss/lahore"


def test_local_tier_collapses_to_its_real_owners() -> None:
    """Three of these feeds are one company. A story carried by all three is
    one teller, and counting it as three is the #641 independence inflation."""
    owners = content_owner_map()
    assert (
        owners["rss-edinburgh-live"] == owners["rss-glasgow-live"] == owners["rss-men-manchester"]
    )
    assert owners["rss-bbc-manchester"] == owners["rss-bbc-uk"]
    # The Pakistani Nation and the Kenyan Nation share a name and nothing else.
    assert owners["rss-nation-lahore"] != owners["rss-nation-kenya"]
    # Everything else in the tier is genuinely separate.
    separate = {
        owners[slug]
        for slug in ("rss-stv-news", "rss-herald-scotland", "rss-scotsman", "rss-capital-fm-kenya")
    }
    assert len(separate) == 4


def test_whole_outlet_local_feeds_claim_no_unmeasured_prior() -> None:
    """#796 sets the bar for `domestic_prior` at 80% domestic over a
    hand-labelled sample of a feed's own uncountried rows. A feed that has
    never run has no such rows, so it cannot have earned one yet — however
    Scottish or Kenyan it obviously is."""
    from app.sources.rss_registry import desk_country_map, domestic_prior_map

    priors, desks = domestic_prior_map(), desk_country_map()
    for slug in (
        "rss-stv-news",
        "rss-herald-scotland",
        "rss-scotsman",
        "rss-capital-fm-kenya",
        "rss-standard-kenya",
    ):
        assert slug not in priors, f"{slug} claims a prior nothing has measured"
        assert slug not in desks, f"{slug} is a masthead feed, not a country section"
