"""Module L3 — RSS news fetchers.

Pulls top news from a curated set of RSS feeds (BBC World, Reuters World, Dawn,
Guardian World, Geo English) so the dashboard map has a real news layer next
to the structural CAMEO / hazard / market data.

These events are **Layer 3** — category=NEWS — so they appear on the
dashboard but never enter the composite scoring (see
``docs/architecture/04-schema.md``). That keeps the OECD/JRC methodology
defensible while letting Basil watch UK / Pakistan / world headlines on
the map alongside the geopolitical (GDELT) and hazard (USGS / GDACS /
FIRMS / EONET) layers.

Each feed is a separate Fetcher subclass so the per-source slug stays
distinct (filters and counts work normally). All share the same parser
helpers below.

Country tagging:

- If the feed carries a default ISO (e.g. BBC UK → ``"GB"``), use it.
- Otherwise the feed-level country is None and downstream enrichment can
  attach one later (URL hint, NER, etc.).

Geolocation:

- Most RSS items have no lat/lon. We do **not** try to geocode the
  headline at fetch time (rate limits, API costs). The map renderer
  falls back to country centroid if lat/lon are null and country is set,
  via the existing ``centroids`` lookup.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import feedparser
import httpx

from app.enrichment.city import city_for
from app.enrichment.sentiment import SENTIMENT_METHOD_VERSION, score_text
from app.models import Category, Event
from app.sources.base import Fetcher

RSS_USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"

# Severity for news is a stable mid-band by default. Headlines do not carry
# magnitudes the way USGS quakes do, and we do not run NLP at fetch time.
# Bumping it higher for keyword hits keeps the colour scale meaningful.
NEWS_DEFAULT_SEVERITY: Final[float] = 0.35
NEWS_KEYWORD_SEVERITY: Final[float] = 0.65
_HIGH_SEVERITY_KEYWORDS: Final[tuple[str, ...]] = (
    "killed",
    "dead",
    "attack",
    "explosion",
    "shooting",
    "stab",
    "crash",
    "earthquake",
    "flood",
    "fire",
    "war",
    "protest",
    "strike",
    "evacuated",
    "wounded",
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_IMG_SRC_RE = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.IGNORECASE)


def _extract_image_url(entry: dict[str, Any], summary_html: str) -> str | None:
    """Best-effort image URL from one RSS entry.

    Order: media:thumbnail (BBC) → media:content (Reuters / Guardian) →
    enclosure links (Dawn / Geo) → first <img> in the summary HTML.
    Returns None when nothing matches — the renderer falls back to a
    coloured letter tile.
    """
    for thumb in entry.get("media_thumbnail") or []:
        if isinstance(thumb, dict) and thumb.get("url"):
            return str(thumb["url"])
    for media in entry.get("media_content") or []:
        if isinstance(media, dict) and media.get("url"):
            url = str(media["url"])
            mtype = str(media.get("type") or "").lower()
            if not mtype or mtype.startswith("image/"):
                return url
    for link in entry.get("links") or []:
        if isinstance(link, dict) and link.get("rel") == "enclosure":
            href = link.get("href")
            mtype = str(link.get("type") or "").lower()
            if href and (not mtype or mtype.startswith("image/")):
                return str(href)
    if summary_html:
        match = _HTML_IMG_SRC_RE.search(summary_html)
        if match:
            return match.group(1)
    return None


@dataclass(frozen=True)
class RssFeedConfig:
    """Per-feed configuration consumed by every RssNewsFetcher subclass."""

    #: Stable source slug. Becomes `events.source`.
    source: str
    #: Public RSS URL.
    url: str
    #: Default ISO 3166-1 alpha-2 attached to every item from this feed, or None.
    default_country: str | None
    #: Pretty name for keyword tagging.
    pretty_name: str


def _strip_html(text: str) -> str:
    """Best-effort HTML strip for RSS summaries."""
    return _HTML_TAG_RE.sub("", text).strip()


def _hash_event_id(source: str, link: str, title: str) -> str:
    """Stable id when the feed does not give us a guid."""
    payload = f"{source}|{link}|{title}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_published(entry: dict[str, Any]) -> datetime | None:
    """Pull a UTC datetime from feedparser's parsed entry, with fallbacks."""
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime(*value[:6], tzinfo=UTC)
            except (TypeError, ValueError):
                continue
    return None


def _severity_for(title: str, summary: str) -> float:
    text = f"{title} {summary}".lower()
    for kw in _HIGH_SEVERITY_KEYWORDS:
        if kw in text:
            return NEWS_KEYWORD_SEVERITY
    return NEWS_DEFAULT_SEVERITY


def entry_to_event(
    entry: dict[str, Any], *, config: RssFeedConfig, fetched_at: datetime
) -> Event | None:
    """Pure transformation: one RSS entry → canonical ``Event``."""
    title = (entry.get("title") or "").strip()
    if not title:
        return None
    link = (entry.get("link") or "").strip() or None
    raw_summary = entry.get("summary") or entry.get("description") or ""
    summary = _strip_html(raw_summary) if raw_summary else ""
    image_url = _extract_image_url(entry, raw_summary)

    occurred_at = _parse_published(entry) or fetched_at
    guid = (entry.get("id") or entry.get("guid") or "").strip()
    source_event_id = guid or _hash_event_id(config.source, link or "", title)

    severity = _severity_for(title, summary)

    # Offline city pinpoint: scan title + summary for any of ~1.2 k known
    # populated places. When the feed declares a default country, prefer
    # cities in that country on name collisions (Cambridge UK > Cambridge MA
    # on a BBC UK feed). See app/enrichment/city.py + issue #112.
    city = city_for(f"{title} {summary}", country_hint=config.default_country)
    lat = city.lat if city else None
    lon = city.lon if city else None
    country = (city.iso if city else None) or config.default_country

    # VADER sentiment over title + summary. ``compound`` ∈ [-1, 1].
    # See app/enrichment/sentiment.py + issue #126. Label is a UI
    # convenience derived via VADER's published cut-offs.
    sentiment = score_text(f"{title}. {summary}".strip())

    payload: dict[str, Any] = {
        "title": title,
        "source_url": link,
        "summary": summary[:500] if summary else None,
        "feed_name": config.pretty_name,
        "published_at": occurred_at.isoformat(),
        "guid": guid or None,
        "city": city.name if city else None,
        "image_url": image_url,
        "sentiment": sentiment.compound if sentiment else None,
        "sentiment_label": sentiment.label if sentiment else None,
        "enrichment_meta": {"sentiment_model": SENTIMENT_METHOD_VERSION},
    }

    return Event(
        source=config.source,
        source_event_id=source_event_id,
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.NEWS,
        severity=severity,
        confidence=None,
        keywords=["news", config.source, config.pretty_name.lower()],
        country=country,
        lat=lat,
        lon=lon,
        payload=payload,
    )


def parse_rss_body(body: str, *, config: RssFeedConfig, fetched_at: datetime) -> list[Event]:
    """Parse an RSS / Atom body into ``Event`` rows. Silent on bad input."""
    if not body:
        return []
    parsed = feedparser.parse(body)
    if parsed.bozo and not parsed.entries:
        return []
    events: list[Event] = []
    for entry in parsed.entries:
        event = entry_to_event(dict(entry), config=config, fetched_at=fetched_at)
        if event is not None:
            events.append(event)
    return events


class RssNewsFetcher(Fetcher):
    """Base class for every RSS news fetcher. Subclasses set ``config``."""

    name: str  # set by subclass
    queue = "slow"
    config: RssFeedConfig

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> list[Event]:
        fetched_at = datetime.now(UTC)
        with httpx.Client(
            timeout=self.timeout_seconds,
            headers={"User-Agent": RSS_USER_AGENT},
            # Several feeds (Dawn, others) 301 to a CDN URL on first hit;
            # follow up to 3 hops so we land on the actual XML.
            follow_redirects=True,
        ) as client:
            response = client.get(self.config.url)
            response.raise_for_status()
            return parse_rss_body(response.text, config=self.config, fetched_at=fetched_at)

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return (
            f"/mnt/data/parquet/{self.name}/year={now.year}"
            f"/month={now.month:02d}/day={now.day:02d}/"
        )


# ---------------------------------------------------------------------------
# Per-feed subclasses
# ---------------------------------------------------------------------------


class BBCWorldNewsFetcher(RssNewsFetcher):
    name = "rss-bbc-world"
    config = RssFeedConfig(
        source="rss-bbc-world",
        url="https://feeds.bbci.co.uk/news/world/rss.xml",
        default_country=None,  # World feed
        pretty_name="BBC World",
    )


class BBCUKNewsFetcher(RssNewsFetcher):
    name = "rss-bbc-uk"
    config = RssFeedConfig(
        source="rss-bbc-uk",
        url="https://feeds.bbci.co.uk/news/uk/rss.xml",
        default_country="GB",
        pretty_name="BBC UK",
    )


class ReutersWorldNewsFetcher(RssNewsFetcher):
    name = "rss-reuters-world"
    config = RssFeedConfig(
        source="rss-reuters-world",
        # Reuters retired their own RSS in 2024; the Yahoo/News mirror remains
        # the most stable public Reuters world-news feed.
        url="https://news.yahoo.com/rss/world",
        default_country=None,
        pretty_name="Reuters / Yahoo World",
    )


class DawnNewsFetcher(RssNewsFetcher):
    name = "rss-dawn"
    config = RssFeedConfig(
        source="rss-dawn",
        url="https://www.dawn.com/feed",
        default_country="PK",
        pretty_name="Dawn",
    )


class GuardianWorldNewsFetcher(RssNewsFetcher):
    name = "rss-guardian-world"
    config = RssFeedConfig(
        source="rss-guardian-world",
        url="https://www.theguardian.com/world/rss",
        default_country=None,
        pretty_name="Guardian World",
    )


class GeoEnglishNewsFetcher(RssNewsFetcher):
    name = "rss-geo-english"
    config = RssFeedConfig(
        source="rss-geo-english",
        url="https://www.geo.tv/rss/1/0",
        default_country="PK",
        pretty_name="Geo English",
    )
