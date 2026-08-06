"""Generic RSS registry.

Replaces the per-feed Python subclasses with a JSON-driven config so
adding a new RSS source is one entry in ``rss_feeds.json``, not a new
fetcher class + tests + beat-schedule entry. See issue #158.

The existing six RSS slugs (BBC World, BBC UK, Reuters / Yahoo,
Dawn, Guardian, Geo) keep their ``source`` strings stable so existing
``events`` rows aren't orphaned by the rename.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.sources.rss_news_fetcher import RssFeedConfig, RssNewsFetcher

_FEEDS_PATH = Path(__file__).parent / "rss_feeds.json"


def load_feed_configs(*, enabled_only: bool = False) -> list[RssFeedConfig]:
    """Read ``rss_feeds.json`` and produce one ``RssFeedConfig`` per entry.

    The cadence_min field is consumed by the beat-schedule generator in
    ``app.tasks`` — not by the fetcher itself — so it lives alongside
    the per-feed metadata but is exposed as a tuple-of-dicts via
    ``feed_cadence_map`` for the scheduler.

    ``enabled_only`` (#490) is for the fetch/schedule paths: parked feeds
    (``"enabled": false`` — dead URL or network-blocked) are skipped there,
    but stay in the default listing so pretty names, owners, and classes keep
    resolving for their historical events rows.
    """
    from app.sources.rss_news_fetcher import RssFeedConfig

    raw = json.loads(_FEEDS_PATH.read_text(encoding="utf-8"))
    out: list[RssFeedConfig] = []
    for entry in raw:
        if enabled_only and entry.get("enabled") is False:
            continue
        out.append(
            RssFeedConfig(
                source=entry["source"],
                url=entry["url"],
                default_country=entry.get("default_country"),
                pretty_name=entry["pretty_name"],
                desk_country=entry.get("desk_country"),
                domestic_prior=entry.get("domestic_prior"),
            )
        )
    return out


def content_owner_map() -> dict[str, str]:
    """Source slug → owner of the *words* the feed carries (WS-C step 2, #355).

    ``syndication`` wins over ``owner``: the Yahoo-hosted feed republishes
    Reuters wire, so its content owner is ``reuters``.

    Consumers must **not** fall back to the source slug. This docstring used to
    say an unmapped feed "counts as its own owner and can never inflate
    independence" — that fallback is precisely how independence inflates (#641).
    `owner_count` feeds an exponential confidence formula, so a source asserting
    its own independence because nobody recorded an owner for it is the whole
    failure. See `app.stories.independence`.
    """
    raw = json.loads(_FEEDS_PATH.read_text(encoding="utf-8"))
    return {entry["source"]: entry.get("syndication") or entry["owner"] for entry in raw}


def outlet_country_map() -> dict[str, str]:
    """Source slug → the outlet's *origin* country, ISO2 (WS-B step 1, #368).

    Origin = where the editorial voice sits, not what the feed covers
    (``default_country`` is the coverage default used for geotagging). For the
    syndicated Yahoo-hosted feed the origin follows the content owner
    (Reuters → GB). WS-B groups a story's tellings by this to measure
    cross-country narrative divergence.
    """
    raw = json.loads(_FEEDS_PATH.read_text(encoding="utf-8"))
    return {entry["source"]: entry["country"] for entry in raw}


def domestic_prior_map() -> dict[str, str]:
    """Source slug → the country a feed is *usually* about, ISO2 (#796).

    A weaker claim than ``desk_country``, and deliberately a separate key.
    ``desk_country`` is structural — the feed URL is that country's section,
    so every story in it is about that country by construction. This is
    statistical: a national masthead's general feed, measured to be mostly
    domestic. Conflating the two would hide which kind of claim a stored
    row rests on, so the resolver reports them as different bases.

    A feed earns this by measurement, never by looking national. The bar is
    **at least 80% domestic in a hand-labelled sample of at least twelve of
    that feed's own uncountried rows** — uncountried, because those are the
    only rows the prior will ever touch. Sampling what a feed *did* place
    measures the wrong population: a row gets placed by naming a foreign
    country, so the placed set over-represents exactly the stories the
    prior would get wrong.

    Measured against the live table over seven days:

    ==================  ====  ================  ==============
    feed                home  domestic          uncountried/7d
    ==================  ====  ================  ==============
    rss-the-hindu       IN    15 / 15   (100%)             689
    rss-tribune-pk      PK    10 / 12    (83%)             377
    rss-sabc-news       ZA    12 / 12   (100%)             135
    rss-yonhap-en       KR    15 / 15   (100%)              40
    ------------------  ----  ----------------  --------------
    rss-antara-en       ID    20 / 30    (67%)              64
    rss-times-of-india  IN     6 / 12    (50%)             288
    rss-daily-sabah     TR     5 / 12    (42%)              74
    rss-geo-english     PK     0 / 12     (0%)             252
    ==================  ====  ================  ==============

    The four below the line are why the bar exists rather than a rule of
    thumb about national mastheads. ``geo-english`` is Pakistani, is the
    third-largest contributor to the gap, and its uncountried tail is an
    entertainment desk — so the prior would stamp Pakistan on 252 rows a
    week that have nothing to do with it, which is #166 exactly.

    Like ``desk_country`` this applies only when the text yields no
    geography at all, and it never produces coordinates: knowing which
    country a story is about is not knowing where it happened.
    """
    raw = json.loads(_FEEDS_PATH.read_text(encoding="utf-8"))
    return {
        entry["source"]: entry["domestic_prior"] for entry in raw if entry.get("domestic_prior")
    }


def desk_country_map() -> dict[str, str]:
    """Source slug → the country this feed's *section* is about, ISO2 (#717).

    Distinct from both ``country`` (where the editorial voice sits) and
    ``default_country`` (a geotagging bias). ``desk_country`` is the much
    narrower claim that every story in the feed is about one country,
    because the feed URL is that country's section — BBC's /news/uk, the
    Nation's /kenya, SCMP's China desk.

    ``app.enrichment.geo`` uses it as a last resort, only when a headline
    yields no geography at all. Applied any wider it re-creates the #166
    centroid blob, where a national paper's world coverage was stamped
    with the paper's own flag.

    Feeds without the key are absent from the mapping.
    """
    raw = json.loads(_FEEDS_PATH.read_text(encoding="utf-8"))
    return {entry["source"]: entry["desk_country"] for entry in raw if entry.get("desk_country")}


def outlet_class_map() -> dict[str, str]:
    """Source slug → outlet class (#477): mainstream, state, regional, or
    independent.

    First-pass ownership-based labels — transparent bias, not a truth ranking:
    "state" means state-owned/controlled or government-aligned editorial line,
    "independent" the non-MSM/alt outlets, "regional" national outlets outside
    the global wire circle. Unmapped slugs count as mainstream.
    """
    raw = json.loads(_FEEDS_PATH.read_text(encoding="utf-8"))
    return {entry["source"]: entry.get("class") or "mainstream" for entry in raw}


def feed_cadence_map() -> dict[str, int]:
    """Source slug → cadence in minutes. Drives ``app.tasks`` beat schedule.

    Parked feeds (#490) are excluded — a dead URL must not burn a fetch slot
    every cycle."""
    raw = json.loads(_FEEDS_PATH.read_text(encoding="utf-8"))
    return {
        entry["source"]: int(entry.get("cadence_min", 60))
        for entry in raw
        if entry.get("enabled") is not False
    }


def build_rss_fetchers() -> dict[str, RssNewsFetcher]:
    """One ``RssNewsFetcher`` instance per configured feed, keyed by slug.

    Each instance is a dynamically named subclass of ``RssNewsFetcher``
    so it satisfies the ``Fetcher`` contract (``name`` + ``config``
    class attributes) without hand-writing a class per feed.
    """
    from app.sources.rss_news_fetcher import RssNewsFetcher

    out: dict[str, RssNewsFetcher] = {}
    for cfg in load_feed_configs(enabled_only=True):
        cls = type(
            f"RssFeed_{cfg.source.replace('-', '_')}",
            (RssNewsFetcher,),
            {"name": cfg.source, "config": cfg, "queue": "slow"},
        )
        out[cfg.source] = cls()
    return out
