"""Module L3 — RSS news fetchers.

Pulls top news from a curated set of RSS feeds (BBC World, Reuters World, Dawn,
Guardian World, Geo English) so the dashboard map has a real news layer next
to the structural CAMEO / hazard / market data.

These events are **Layer 3** — category=NEWS — so they appear on the
dashboard but never enter the composite scoring (see
``docs/architecture/04-schema.md``). That keeps the OECD/JRC methodology
defensible while letting the operator watch UK / Pakistan / world headlines on
the map alongside the geopolitical (GDELT) and hazard (USGS / GDACS /
FIRMS / EONET) layers.

Each feed is a separate Fetcher subclass so the per-source slug stays
distinct (filters and counts work normally). All share the same parser
helpers below.

Country tagging:

- Country comes from ``app/enrichment/geo.py``, which scores country
  names, demonyms, regions, then the city gazetteer, then the feed's
  ``desk_country``. It answers "which country is this story about",
  not "which city did the text name" — those diverge on most
  foreign-desk journalism, which is what #717 measured.
- A story naming several countries and being about none of them gets
  no country at all. Absence is a real answer; roughly 40% of
  headlines have no geography.
- ``default_country`` still only biases city-name collisions
  (Cambridge UK over Cambridge MA). It is never a blanket fallback —
  see migration ``0002`` and ``news_scope``.

Geolocation:

- Most RSS items have no upstream lat/lon. Fetch time uses only bundled city
  and region data. The bounded ``enrich_news_places`` worker may later upgrade
  one explicit named building/street/site through the persistent Wikidata
  cache (#745). Unknown never gets an invented country-centre marker.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import feedparser
import httpx

from app.enrichment import translation
from app.enrichment.geo import GEO_METHOD_VERSION, resolve_geo, resolved_news_scope
from app.enrichment.ner import (
    NER_METHOD_VERSION,
    entities_to_payload,
    extract_entities,
)
from app.enrichment.ner import (
    is_available as ner_available,
)
from app.enrichment.sentiment import SENTIMENT_METHOD_VERSION, score_text
from app.models import Category, Event
from app.severity import news as news_severity
from app.sources.base import Fetcher
from app.sources.rss_identity import canonical_rss_event_id

RSS_USER_AGENT: Final[str] = "OSINT-project/0.0.1 (academic)"

# Severity for news is a stable mid-band by default. Headlines do not carry
# magnitudes the way USGS quakes do, and we do not run NLP at fetch time.
# Bumping it higher for keyword hits keeps the colour scale meaningful.
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
    #: ISO2 this feed's *section* is about, when the feed is a country desk
    #: (BBC /news/uk → GB). Used only as the resolver's last resort. None
    #: for world desks and general national papers. See #717.
    desk_country: str | None = None
    domestic_prior: str | None = None
    #: What this desk publishes in. Anything but English routes the headline
    #: through translation before geo, severity and clustering see it — all of
    #: which are Latin-script only, so an Arabic desk resolved 0 of 25 rows
    #: before this existed (#835).
    language: str = "en"


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


def translate_text(prompt: str, *, model: str) -> str | None:
    """One prompt → the model's plain-text answer, or None.

    Kept here rather than in `app.enrichment.translation` so that module stays
    free of transport and every rule in it is testable without a network. The
    brain's client already owns talking to Ollama; this is the thin adapter
    between its signature and the injected `generate` the translator expects.
    """
    from app.brain import client

    return client.generate_plain(prompt, model=model)


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

    # Translate before anything reads the words (#835). The severity keywords,
    # the geo resolver and the story tokenizer are all English, so a desk that
    # publishes in Arabic resolved 0 of 25 rows to a country and scored one
    # constant severity. The original is kept verbatim in the payload; a
    # failure keeps the original headline and records the attempt.
    translated = translation.apply(
        {"title": title},
        declared_language=config.language,
        generate=translate_text,
    )
    title = str(translated.get("title") or title)
    translation_fields = {
        key: translated[key] for key in ("title_original", "title_translation") if key in translated
    }

    published_at = _parse_published(entry)
    occurred_at = published_at or fetched_at
    guid = (entry.get("id") or entry.get("guid") or "").strip()
    source_event_id = (
        canonical_rss_event_id(guid, link)
        if guid
        else _hash_event_id(config.source, link or "", title)
    )

    # Graded fallback on the ingest path (#591): separates fatal from violent
    # from disruptive instead of flattening all three onto one value, and
    # states its reason. The LLM batch pass upgrades it afterwards.
    verdict = news_severity.keyword_verdict(title, summary)

    # Which country is this story *about*? Scored over title + summary:
    # country names and demonyms, then regions, then the city gazetteer,
    # then the feed's own desk. A story naming several countries and being
    # about none of them resolves to nothing on purpose. See
    # app/enrichment/geo.py + issue #717.
    geo = resolve_geo(
        title,
        summary,
        desk_country=config.desk_country,
        domestic_prior=config.domestic_prior,
        city_hint=config.default_country,
    )
    country = geo.iso
    lat = geo.lat
    lon = geo.lon

    # news_scope keeps its three values because MapPane reads it to decide
    # the country-centroid fallback (#166). See
    # app.enrichment.geo.resolved_news_scope for why "local" also requires
    # coordinates, not just a matching country.
    news_scope = resolved_news_scope(country, lat, lon, config.default_country)

    # VADER sentiment over title + summary. ``compound`` ∈ [-1, 1].
    # See app/enrichment/sentiment.py + issue #126. Label is a UI
    # convenience derived via VADER's published cut-offs.
    sentiment = score_text(f"{title}. {summary}".strip())

    # spaCy NER over title + summary (#154). Falls back to an empty
    # list when spacy or the model wheel isn't installed — see
    # app/enrichment/ner.py.
    entities = extract_entities(f"{title}. {summary}".strip())

    payload: dict[str, Any] = {
        "title": title,
        "source_url": link,
        "summary": summary[:500] if summary else None,
        "feed_name": config.pretty_name,
        "published_at": occurred_at.isoformat(),
        "published_from_feed": published_at is not None,
        "guid": guid or None,
        "city": geo.city,
        **translation_fields,
        "geo_basis": geo.basis,
        "image_url": image_url,
        "sentiment": sentiment.compound if sentiment else None,
        "sentiment_label": sentiment.label if sentiment else None,
        "news_scope": news_scope,
        "entities": entities_to_payload(entities),
        **verdict.as_payload(),
        "enrichment_meta": {
            "sentiment_model": SENTIMENT_METHOD_VERSION,
            "ner_model": NER_METHOD_VERSION if ner_available() else "none",
            "geo_model": GEO_METHOD_VERSION,
        },
    }

    return Event(
        source=config.source,
        source_event_id=source_event_id,
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.NEWS,
        severity=verdict.value,
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
        desk_country="GB",
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
