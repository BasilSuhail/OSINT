"""One query, two kinds of answer (#779).

A search term is either a place or it is not, and the system already knows
which — it ships a city gazetteer, region points and the set of countries
that have events. A place is a camera move; anything else is a list.

Both halves are deliberately exact rather than fuzzy. Trigram similarity
over 464k rows returns things that merely *look* like the query, and a
search that answers a question you did not ask is worse than one that
returns nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.article_collapse import ARTICLE_KEY_SQL, SURVIVOR_ORDER_SQL
from app.enrichment.country import country_name
from app.enrichment.name_collision import is_collision
from app.readable_claim import READABLE_CLAIM_SQL
from app.search_terms import Topic, topic_for

_DATA = Path(__file__).parent / "enrichment" / "data"

#: Shortest query worth running. One character matches half the gazetteer and
#: every article in the corpus; it is a keystroke, not a question.
MIN_QUERY_LEN = 2

#: How much wider than the page to fetch when collisions will be filtered out
#: of it (#800). Three covers the worst case seen — half of Edinburgh's
#: results were the dukedom — and costs about a millisecond at this index
#: size, so it is not worth tuning further.
OVERFETCH = 3

#: Must match `migrations/versions/0029_event_search_topics.py` exactly, or
#: Postgres will not use the GIN index — an expression index is only chosen
#: when the query's expression is character-identical to the indexed one.
#:
#: Title and summary are the RSS fields, and for a long time they were the
#: whole vector — which meant search saw only the sources that ship prose.
#: The rest of these are where the other feeds put the words a reader would
#: recognise: `place` is USGS' "10 km SW of…", `eventname` and `country_name`
#: are GDACS', `geo_name` and `action_label` are GDELT's, `threat` is the
#: malware classification. Rows with none of them produce an empty tsvector,
#: and GIN stores no entries for one, so the fire detections that make up most
#: of the table cost this index nothing. They are found by keyword instead.
SEARCH_VECTOR_SQL = (
    "to_tsvector('english', "
    "coalesce(payload->>'title', '') || ' ' || "
    "coalesce(payload->>'summary', '') || ' ' || "
    "coalesce(payload->>'place', '') || ' ' || "
    "coalesce(payload->>'eventname', '') || ' ' || "
    "coalesce(payload->>'country_name', '') || ' ' || "
    "coalesce(payload->>'geo_name', '') || ' ' || "
    "coalesce(payload->>'action_label', '') || ' ' || "
    "coalesce(payload->>'threat', ''))"
)


@dataclass(frozen=True)
class PlaceHit:
    """A place the map can be moved to."""

    name: str
    lat: float
    lon: float
    country: str | None
    #: "city" | "region" | "country" — drives how far the map zooms in.
    kind: Literal["city", "region", "country"]
    #: What distinguishes this candidate from the others sharing its name.
    #: The whole point of listing rather than guessing: "Brooklyn, US" beside
    #: "Brooklyn, ZA" is the difference between navigating and lying.
    context: str = ""
    population: int = 0


@dataclass
class SearchResult:
    places: list[PlaceHit] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    #: True when the query named a place but more than one place answers to
    #: that name. The caller must ask rather than pick.
    ambiguous: bool = False


def _norm(text_in: str) -> str:
    return " ".join(text_in.strip().lower().split())


@lru_cache(maxsize=1)
def _city_index() -> dict[str, list[PlaceHit]]:
    """Lowercased name → every city answering to it, largest first.

    Alternate spellings are indexed alongside primary names, so "Bombay"
    finds Mumbai and "Peking" finds Beijing.
    """
    with (_DATA / "cities.json").open(encoding="utf-8") as fh:
        rows = json.load(fh)
    idx: dict[str, list[PlaceHit]] = {}
    for row in rows:
        iso = row.get("iso") or None
        hit = PlaceHit(
            name=row["n"],
            lat=float(row["lat"]),
            lon=float(row["lon"]),
            country=iso,
            kind="city",
            context=country_name(iso) or (iso or ""),
            population=int(row.get("pop") or 0),
        )
        for spelling in [row["n"], *(row.get("alt") or [])]:
            idx.setdefault(_norm(spelling), []).append(hit)
    for key in idx:
        idx[key].sort(key=lambda h: -h.population)
    return idx


@lru_cache(maxsize=1)
def _region_index() -> dict[str, list[PlaceHit]]:
    try:
        with (_DATA / "region_coords.json").open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    idx: dict[str, list[PlaceHit]] = {}
    for iso, regions in raw.items():
        for name, point in regions.items():
            idx.setdefault(_norm(name), []).append(
                PlaceHit(
                    name=name.title(),
                    lat=float(point[0]),
                    lon=float(point[1]),
                    country=iso,
                    kind="region",
                    context=country_name(iso) or iso,
                )
            )
    return idx


#: Points in region_coords that name a building rather than an area. They
#: earn their place there — a story naming the Kremlin should pin on Moscow
#: — but they are useless as captions. The nearest anchor to central London
#: is Whitehall, and "London — Whitehall" describes nothing.
_NOT_A_REGION = frozenset(
    {
        "whitehall",
        "westminster",
        "pentagon",
        "white house",
        "capitol hill",
        "kremlin",
        "knesset",
        "bundestag",
        "elysee",
        "dail",
    }
)


@lru_cache(maxsize=1)
def _region_points_by_country() -> dict[str, list[tuple[str, float, float]]]:
    """ISO → [(region name, lat, lon)], for naming which one a city sits in."""
    out: dict[str, list[tuple[str, float, float]]] = {}
    for key, hits in _region_index().items():
        if key in _NOT_A_REGION:
            continue
        for hit in hits:
            if hit.country:
                out.setdefault(hit.country, []).append((hit.name, hit.lat, hit.lon))
    return out


def _nearest_region(lat: float, lon: float, iso: str | None) -> str | None:
    """Name the region a point falls nearest, within the same country.

    Five Springfields all captioned "United States of America" tell the
    reader nothing — the caption has to be the thing that differs. The
    gazetteer carries no admin-1 field, but 48 US states and 55 countries
    do have region points, and nearest-of-those names the state well enough
    to choose by.

    Nearest, not containing: these are label anchors, not polygons. A city
    near a state line can be captioned with its neighbour, so the distance
    cap keeps a wrong answer local rather than wild, and population and
    coordinates remain in the payload for anyone who needs certainty.
    """
    if not iso:
        return None
    candidates = _region_points_by_country().get(iso)
    if not candidates:
        return None
    best, best_d2 = None, None
    for name, rlat, rlon in candidates:
        d2 = (rlat - lat) ** 2 + ((rlon - lon) * 0.66) ** 2
        if best_d2 is None or d2 < best_d2:
            best, best_d2 = name, d2
    #: ~6 degrees. Beyond that the nearest anchor is not a description.
    return best if best_d2 is not None and best_d2 < 36 else None


def find_places(query: str, *, limit: int = 8) -> list[PlaceHit]:
    """Places answering to ``query``, best first.

    Exact name matches come before prefix matches, and larger places before
    smaller ones, because "London" should not offer London, Ohio first. No
    fuzzy matching: a place the reader did not type is not a place they
    asked for.
    """
    q = _norm(query)
    if len(q) < MIN_QUERY_LEN:
        return []

    exact: list[PlaceHit] = []
    prefix: list[PlaceHit] = []
    for index in (_city_index(), _region_index()):
        for key, hits in index.items():
            if key == q:
                exact.extend(hits)
            elif key.startswith(q):
                prefix.extend(hits)

    exact.sort(key=lambda h: -h.population)
    prefix.sort(key=lambda h: (-h.population, h.name))

    out: list[PlaceHit] = []
    #: Keyed on position, not name-and-country. There are five Springfields in
    #: the United States and they are five different places; a key of
    #: (name, country) folded them into one and answered an ambiguous query
    #: with a single confident wrong result — the failure this whole listing
    #: behaviour exists to prevent.
    seen: set[tuple[float, float]] = set()
    for hit in exact + prefix:
        key = (round(hit.lat, 3), round(hit.lon, 3))
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
        if len(out) >= limit:
            break

    #: Add a region only where the country cannot already tell two candidates
    #: apart — five Springfields all in the United States. London appears in
    #: three countries and is separated by that alone, and reaching for a
    #: region there produced "London — Wales": England was removed as a region
    #: in #725 for being country-sized, so the nearest UK anchor to London is
    #: the wrong side of a border. A caption that is not needed is a caption
    #: that can only be wrong.
    contested: dict[tuple[str, str | None], int] = {}
    for hit in out:
        key = (hit.name.lower(), hit.country)
        contested[key] = contested.get(key, 0) + 1
    detailed: list[PlaceHit] = []
    for hit in out:
        if contested[(hit.name.lower(), hit.country)] > 1 and hit.kind == "city":
            region = _nearest_region(hit.lat, hit.lon, hit.country)
            if region:
                hit = replace(hit, context=f"{region.title()}, {hit.context}")
        detailed.append(hit)
    return detailed


def search_events(
    session: Session,
    query: str,
    *,
    limit: int = 40,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Events whose text matches ``query``, most relevant first.

    `plainto_tsquery` rather than raw `to_tsquery`: it takes what a person
    typed, including spaces and punctuation, and never raises on input a
    reader could plausibly enter. Ranking is `ts_rank_cd` with recency as
    the tie-break, so a strong old match still beats a weak new one but
    today wins an even contest.
    """
    q = query.strip()
    if len(_norm(q)) < MIN_QUERY_LEN:
        return []

    sql = text(
        f"""
        SELECT * FROM (
            SELECT id, source, source_event_id, category, severity, country,
                   lat, lon, occurred_at, fetched_at, keywords, payload,
                   ts_rank_cd({SEARCH_VECTOR_SQL}, plainto_tsquery('english', :q)) AS rank,
                   row_number() OVER (
                       PARTITION BY {ARTICLE_KEY_SQL}
                       ORDER BY {SURVIVOR_ORDER_SQL}
                   ) AS relation_rank,
                   count(*) OVER (PARTITION BY {ARTICLE_KEY_SQL}) AS relation_count
            FROM events
            WHERE occurred_at > now() - make_interval(days => :days)
              AND {SEARCH_VECTOR_SQL} @@ plainto_tsquery('english', :q)
              AND {READABLE_CLAIM_SQL}
        ) matches
        WHERE relation_rank = 1
        ORDER BY rank DESC, occurred_at DESC
        LIMIT :limit
        """
    )
    rows = session.execute(sql, {"q": q, "days": days, "limit": limit}).mappings().all()
    # `relation_rank` is scaffolding for the collapse; `relation_count` is the
    # part a reader could want to know, so only the second one travels.
    return [{k: v for k, v in row.items() if k != "relation_rank"} for row in rows]


def topic_events(
    session: Session,
    topic: Topic,
    *,
    limit: int = 40,
    days: int = 30,
) -> list[dict[str, Any]]:
    """The most recent events of a kind, newest first.

    A separate query rather than an `OR` bolted onto the full-text one. The
    two ask different questions: full-text ranks how well a row matches words,
    and a topic has no words to match — every fire detection is equally a fire
    detection, so the only sane order is by time. Bolting them together also
    means ranking a million rows whose rank is zero by construction, where two
    bounded queries each stop at the page they were asked for.
    """
    where = []
    params: dict[str, Any] = {"days": days, "limit": limit}
    if topic.category:
        where.append("category = :category")
        params["category"] = topic.category
    if topic.keywords:
        where.append("keywords && :keywords")
        #: Sorted so the parameter is stable between calls; the set's own
        #: iteration order is not.
        params["keywords"] = sorted(topic.keywords)
    if not where:
        return []

    #: Take the page first, collapse it second. A window function is evaluated
    #: over every row the WHERE admits, before any LIMIT applies — so running
    #: the collapse in the same SELECT partitioned 1.95M fire detections to
    #: return forty of them, and "disasters" took 8.5 seconds. Bounding the set
    #: in a CTE first brought it to single-digit milliseconds.
    #:
    #: The cost is that duplicates are now collapsed within the fetched slice
    #: rather than across the whole window. That is the right trade here: the
    #: collapse exists for GDELT's repeated wire copy, and a topic query is
    #: answering "what kind", where near-identical neighbours are the honest
    #: answer rather than noise.
    params["fetch"] = limit * OVERFETCH
    sql = text(
        f"""
        WITH page AS (
            SELECT id, source, source_event_id, category, severity, country,
                   lat, lon, occurred_at, fetched_at, keywords, payload
            FROM events
            WHERE occurred_at > now() - make_interval(days => :days)
              AND ({" OR ".join(where)})
              AND {READABLE_CLAIM_SQL}
            ORDER BY occurred_at DESC
            LIMIT :fetch
        )
        SELECT * FROM (
            SELECT *, 0::float4 AS rank,
                   row_number() OVER (
                       PARTITION BY {ARTICLE_KEY_SQL}
                       ORDER BY {SURVIVOR_ORDER_SQL}
                   ) AS relation_rank,
                   count(*) OVER (PARTITION BY {ARTICLE_KEY_SQL}) AS relation_count
            FROM page
        ) matches
        WHERE relation_rank = 1
        ORDER BY occurred_at DESC
        LIMIT :limit
        """
    )
    rows = session.execute(sql, params).mappings().all()
    return [{k: v for k, v in row.items() if k != "relation_rank"} for row in rows]


def _row_text(row: dict[str, Any]) -> str:
    """The text a reader would see on this row, for collision checking."""
    payload = row.get("payload") or {}
    parts = (payload.get("title"), payload.get("summary"), payload.get("action_label"))
    return " ".join(str(p) for p in parts if p)


def search(session: Session, query: str, *, limit: int = 40) -> SearchResult:
    """Answer a query with places, content, or both.

    A term can legitimately be both — "Manchester" is a city and a word in
    stories about the club — so both halves run and the caller decides what
    to show. Only the reader knows which they meant.
    """
    if len(_norm(query)) < MIN_QUERY_LEN:
        return SearchResult()
    places = find_places(query)

    #: A word for a kind of event answers with that kind. Checked before
    #: full-text because the words do not overlap: "disasters" and "wildfire"
    #: match no headline in the corpus, so running both would spend a query to
    #: return nothing and then hand back the topic anyway.
    topic = topic_for(query)
    if topic is not None:
        return SearchResult(
            places=places,
            events=topic_events(session, topic, limit=limit),
            ambiguous=len(places) > 1,
        )

    #: A place name is also a title, and full-text cannot tell them apart:
    #: half of "edinburgh" came back as the Duke and Duchess of Edinburgh
    #: (#800). Filtered only when the query actually names a place — asking
    #: for "duke" must still return dukes — and only when every mention in
    #: a row is a title, so a story about both the duke and the city
    #: survives.
    #:
    #: Fetch wide, filter, then cut to the page. Filtering a page-sized
    #: fetch silently halved the page: Edinburgh went from forty rows to
    #: twenty, so removing the noise cost the reader depth. Measured on the
    #: live index, tripling the fetch costs about a millisecond — edinburgh
    #: 4.8 ms to 4.5, ceasefire 17.8 to 19.5, amazon 6.9 to 8.2 — so there
    #: was no trade-off to make.
    if places:
        rows = search_events(session, query, limit=limit * OVERFETCH)
        needle = _norm(query)
        events = [row for row in rows if not is_collision(_row_text(row), needle)][:limit]
    else:
        events = search_events(session, query, limit=limit)

    return SearchResult(
        places=places,
        events=events,
        ambiguous=len(places) > 1,
    )
