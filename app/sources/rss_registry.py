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

from app.sources.rss_news_fetcher import RssFeedConfig, RssNewsFetcher

_FEEDS_PATH = Path(__file__).parent / "rss_feeds.json"


def load_feed_configs() -> list[RssFeedConfig]:
    """Read ``rss_feeds.json`` and produce one ``RssFeedConfig`` per entry.

    The cadence_min field is consumed by the beat-schedule generator in
    ``app.tasks`` — not by the fetcher itself — so it lives alongside
    the per-feed metadata but is exposed as a tuple-of-dicts via
    ``feed_cadence_map`` for the scheduler.
    """
    raw = json.loads(_FEEDS_PATH.read_text(encoding="utf-8"))
    out: list[RssFeedConfig] = []
    for entry in raw:
        out.append(
            RssFeedConfig(
                source=entry["source"],
                url=entry["url"],
                default_country=entry.get("default_country"),
                pretty_name=entry["pretty_name"],
            )
        )
    return out


def content_owner_map() -> dict[str, str]:
    """Source slug → owner of the *words* the feed carries (WS-C step 2, #355).

    ``syndication`` wins over ``owner``: the Yahoo-hosted feed republishes
    Reuters wire, so its content owner is ``reuters``. Consumers should fall
    back to the source slug for slugs not in this map — an unmapped feed
    counts as its own owner and can never inflate independence.
    """
    raw = json.loads(_FEEDS_PATH.read_text(encoding="utf-8"))
    return {entry["source"]: entry.get("syndication") or entry["owner"] for entry in raw}


def feed_cadence_map() -> dict[str, int]:
    """Source slug → cadence in minutes. Drives ``app.tasks`` beat schedule."""
    raw = json.loads(_FEEDS_PATH.read_text(encoding="utf-8"))
    return {entry["source"]: int(entry.get("cadence_min", 60)) for entry in raw}


def build_rss_fetchers() -> dict[str, RssNewsFetcher]:
    """One ``RssNewsFetcher`` instance per configured feed, keyed by slug.

    Each instance is a dynamically named subclass of ``RssNewsFetcher``
    so it satisfies the ``Fetcher`` contract (``name`` + ``config``
    class attributes) without hand-writing a class per feed.
    """
    out: dict[str, RssNewsFetcher] = {}
    for cfg in load_feed_configs():
        cls = type(
            f"RssFeed_{cfg.source.replace('-', '_')}",
            (RssNewsFetcher,),
            {"name": cfg.source, "config": cfg, "queue": "slow"},
        )
        out[cfg.source] = cls()
    return out
