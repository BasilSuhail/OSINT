"""Strict named-place resolution for RSS news (#745, child of #717).

The ingest-time resolver can truthfully place a story at a city or region.
This module is the slower second pass: it upgrades an explicit venue, building,
street, or site to its own coordinate when Wikidata proves the identity.

The gate is deliberately narrow. A result must match the extracted name, name
the already-resolved city in its description, carry coordinates, and sit near
that city. Search rank never decides identity. Unknown and ambiguous places do
not move the marker.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db_models import EventRow, PlaceLookupRow
from app.models import Category, Event

PLACE_METHOD_VERSION: Final[str] = "place.wikidata.v1.0"
WIKIDATA_API_URL: Final[str] = "https://www.wikidata.org/w/api.php"
WIKIDATA_USER_AGENT: Final[str] = (
    "OSINT-ground-truth/1.0 "
    "(https://github.com/BasilSuhail/OSINT; BasilSuhail@users.noreply.github.com)"
)
MAX_LOCALITY_DISTANCE_KM: Final[float] = 75.0
NEGATIVE_CACHE_TTL: Final[timedelta] = timedelta(days=30)
SEARCH_LIMIT: Final[int] = 10
WIKIDATA_MAXLAG: Final[int] = 15
PLACE_SCAN_LIMIT: Final[int] = 2000

PlacePrecision = Literal["building", "street", "site"]
LookupStatus = Literal["resolved", "no_match", "ambiguous"]

_STREET_SUFFIXES: Final[frozenset[str]] = frozenset(
    {"avenue", "boulevard", "drive", "lane", "road", "square", "street"}
)
_SITE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {"gardens", "harbour", "harbor", "marina", "park", "plaza", "port"}
)
_BUILDING_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        "airport",
        "arena",
        "barracks",
        "base",
        "bridge",
        "building",
        "castle",
        "cathedral",
        "center",
        "centre",
        "church",
        "cinema",
        "college",
        "consulate",
        "court",
        "courthouse",
        "dam",
        "embassy",
        "factory",
        "gallery",
        "hall",
        "hospital",
        "hotel",
        "jail",
        "library",
        "mall",
        "market",
        "mine",
        "mosque",
        "museum",
        "palace",
        "parliament",
        "plant",
        "prison",
        "refinery",
        "school",
        "stadium",
        "station",
        "synagogue",
        "temple",
        "terminal",
        "theater",
        "theatre",
        "tower",
        "university",
    }
)
_PLACE_SUFFIXES: Final[frozenset[str]] = _STREET_SUFFIXES | _SITE_SUFFIXES | _BUILDING_SUFFIXES

# A named place ends in a place-kind word and starts with capitalised words.
# Lowercase joiners are allowed inside names ("Bank of England Museum"), but
# ordinary sentence words stop the match ("fire at King's Theatre").
_CURLY_APOSTROPHE: Final[str] = "\N{RIGHT SINGLE QUOTATION MARK}"
_NAME_TOKEN = rf"(?:[A-ZÀ-ÖØ-Þ][\w'{_CURLY_APOSTROPHE}.-]*|[A-Z]{{2,}}|of|the|and|de|la|al|&|St\.?)"
_CANDIDATE_RE = re.compile(
    rf"(?<![\w'{_CURLY_APOSTROPHE}])({_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,6}}?\s+"
    rf"(?i:{'|'.join(sorted(_PLACE_SUFFIXES, key=len, reverse=True))}))\b",
)


@dataclass(frozen=True)
class PlaceCandidate:
    name: str
    precision: PlacePrecision


@dataclass(frozen=True)
class PlaceContext:
    country: str
    city: str
    lat: float
    lon: float


@dataclass(frozen=True)
class PlaceResolution:
    wikidata_id: str
    label: str
    description: str
    lat: float
    lon: float
    precision: PlacePrecision


@dataclass(frozen=True)
class PlaceVerdict:
    status: LookupStatus
    resolution: PlaceResolution | None = None


def normalise_place_name(text: str) -> str:
    """Accent-insensitive comparison form for names and descriptions."""
    folded = unicodedata.normalize("NFKD", text.replace(_CURLY_APOSTROPHE, "'").casefold())
    asciiish = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^\w]+", " ", asciiish).split())


def _precision_for(name: str) -> PlacePrecision:
    suffix = normalise_place_name(name).rsplit(" ", 1)[-1]
    if suffix in _STREET_SUFFIXES:
        return "street"
    if suffix in _SITE_SUFFIXES:
        return "site"
    return "building"


def _clean_candidate(name: str, city: str | None) -> str:
    punctuation = " ,:;-\N{EN DASH}\N{EM DASH}"
    cleaned = " ".join(name.strip(punctuation).split())
    cleaned = re.sub(r"^(?:the|and)\s+", "", cleaned, flags=re.IGNORECASE)
    if city:
        city_words = normalise_place_name(city)
        candidate_words = normalise_place_name(cleaned)
        if candidate_words.startswith(f"{city_words} "):
            # "Edinburgh King's Theatre" carries context plus the actual name.
            cleaned = cleaned.split(maxsplit=len(city.split()))[-1]
    return cleaned


def extract_place_candidates(
    payload: dict[str, Any], *, city: str | None = None
) -> tuple[PlaceCandidate, ...]:
    """Extract conservative explicit-place candidates from one RSS payload.

    The deterministic suffix matcher is primary because spaCy is optional in
    production. Existing FAC entities add coverage, but ORG entities are only
    accepted when they also look like a physical place.
    """
    names: list[str] = []
    parts = (str(payload.get("title") or ""), str(payload.get("summary") or ""))
    text = " ".join(part for part in parts if part)
    names.extend(match.group(1) for match in _CANDIDATE_RE.finditer(text))

    entities = payload.get("entities")
    if isinstance(entities, list):
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            name = str(entity.get("text") or "").strip()
            label = str(entity.get("label") or "").upper()
            suffix = normalise_place_name(name).rsplit(" ", 1)[-1] if name else ""
            if label == "FAC" or (label == "ORG" and suffix in _PLACE_SUFFIXES):
                names.append(name)

    candidates: list[PlaceCandidate] = []
    seen: set[str] = set()
    for raw_name in names:
        name = _clean_candidate(raw_name, city)
        key = normalise_place_name(name)
        if not key or key in seen or len(key.split()) < 2:
            continue
        suffix = key.rsplit(" ", 1)[-1]
        if suffix not in _PLACE_SUFFIXES:
            continue
        seen.add(key)
        candidates.append(PlaceCandidate(name=name, precision=_precision_for(name)))
    return tuple(candidates)


def lookup_key(candidate: PlaceCandidate, context: PlaceContext) -> str:
    material = "|".join(
        (
            PLACE_METHOD_VERSION,
            normalise_place_name(candidate.name),
            context.country.upper(),
            normalise_place_name(context.city),
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _coordinate(entity: dict[str, Any]) -> tuple[float, float] | None:
    claims = entity.get("claims")
    statements = claims.get("P625") if isinstance(claims, dict) else None
    if not isinstance(statements, list):
        return None
    ranked = sorted(
        (
            item
            for item in statements
            if isinstance(item, dict) and item.get("rank") != "deprecated"
        ),
        key=lambda item: item.get("rank") != "preferred",
    )
    for statement in ranked:
        try:
            value = statement["mainsnak"]["datavalue"]["value"]
            lat, lon = float(value["latitude"]), float(value["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    return None


def _entity_ids(entity: dict[str, Any], property_id: str) -> set[str]:
    claims = entity.get("claims")
    statements = claims.get(property_id) if isinstance(claims, dict) else None
    if not isinstance(statements, list):
        return set()
    values: set[str] = set()
    for statement in statements:
        try:
            value = statement["mainsnak"]["datavalue"]["value"]
            entity_id = value["id"]
        except (KeyError, TypeError):
            continue
        if isinstance(entity_id, str):
            values.add(entity_id)
    return values


def _string_claims(entity: dict[str, Any], property_id: str) -> set[str]:
    claims = entity.get("claims")
    statements = claims.get(property_id) if isinstance(claims, dict) else None
    if not isinstance(statements, list):
        return set()
    values: set[str] = set()
    for statement in statements:
        try:
            value = statement["mainsnak"]["datavalue"]["value"]
        except (KeyError, TypeError):
            continue
        if isinstance(value, str):
            values.add(value.upper())
    return values


def _response_object(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("Wikidata returned a non-object response")
    error = body.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "unknown")
        detail = str(error.get("info") or "Wikidata API error")
        # MediaWiki returns maxlag as HTTP 200. It is a retry signal, never a
        # negative place result; raising keeps it out of the cache.
        raise ValueError(f"Wikidata {code}: {detail}")
    return body


def resolve_wikidata_place(
    candidate: PlaceCandidate,
    context: PlaceContext,
    *,
    client: httpx.Client,
) -> PlaceVerdict:
    """Resolve one candidate without trusting search rank."""
    search_response = client.get(
        WIKIDATA_API_URL,
        params={
            "action": "wbsearchentities",
            "search": candidate.name,
            "language": "en",
            "uselang": "en",
            "type": "item",
            "limit": SEARCH_LIMIT,
            "format": "json",
            "maxlag": WIKIDATA_MAXLAG,
        },
    )
    body = _response_object(search_response)
    results = body.get("search")
    if not isinstance(results, list):
        raise ValueError("Wikidata search response has no result list")

    expected_name = normalise_place_name(candidate.name)
    exact: dict[str, dict[str, Any]] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        match = result.get("match")
        matched_text = match.get("text") if isinstance(match, dict) else None
        entity_id = result.get("id")
        is_exact = normalise_place_name(str(matched_text or "")) == expected_name
        if isinstance(entity_id, str) and is_exact:
            exact[entity_id] = result
    if not exact:
        return PlaceVerdict(status="no_match")

    entity_response = client.get(
        WIKIDATA_API_URL,
        params={
            "action": "wbgetentities",
            "ids": "|".join(exact),
            "props": "labels|descriptions|claims",
            "languages": "en",
            "format": "json",
            "maxlag": WIKIDATA_MAXLAG,
        },
    )
    entity_body = _response_object(entity_response)
    entities = entity_body.get("entities")
    if not isinstance(entities, dict):
        raise ValueError("Wikidata entity response has no entity object")

    context_city = normalise_place_name(context.city)
    potential: list[tuple[str, dict[str, Any], float, float, str, set[str]]] = []
    for entity_id, entity in entities.items():
        if entity_id not in exact or not isinstance(entity, dict):
            continue
        coordinate = _coordinate(entity)
        if coordinate is None:
            continue
        description_data = entity.get("descriptions", {}).get("en", {})
        description = str(description_data.get("value") or "")
        description_words = f" {normalise_place_name(description)} "
        if f" {context_city} " not in description_words:
            continue
        lat, lon = coordinate
        if _haversine_km(context.lat, context.lon, lat, lon) > MAX_LOCALITY_DISTANCE_KM:
            continue
        country_ids = _entity_ids(entity, "P17")
        if not country_ids:
            continue
        potential.append((entity_id, entity, lat, lon, description, country_ids))

    if not potential:
        return PlaceVerdict(status="no_match")

    country_ids = sorted({country_id for item in potential for country_id in item[5]})
    country_response = client.get(
        WIKIDATA_API_URL,
        params={
            "action": "wbgetentities",
            "ids": "|".join(country_ids),
            "props": "claims",
            "format": "json",
            "maxlag": WIKIDATA_MAXLAG,
        },
    )
    country_body = _response_object(country_response)
    countries = country_body.get("entities")
    if not isinstance(countries, dict):
        raise ValueError("Wikidata country response has no entity object")
    country_iso = {
        country_id: _string_claims(entity, "P297")
        for country_id, entity in countries.items()
        if isinstance(entity, dict)
    }

    matches: list[PlaceResolution] = []
    for entity_id, entity, lat, lon, description, entity_country_ids in potential:
        supported_isos = {
            iso for country_id in entity_country_ids for iso in country_iso.get(country_id, set())
        }
        if context.country.upper() not in supported_isos:
            continue
        label_data = entity.get("labels", {}).get("en", {})
        label = str(label_data.get("value") or exact[entity_id].get("label") or candidate.name)
        matches.append(
            PlaceResolution(
                wikidata_id=entity_id,
                label=label,
                description=description,
                lat=lat,
                lon=lon,
                precision=candidate.precision,
            )
        )

    if len(matches) == 1:
        return PlaceVerdict(status="resolved", resolution=matches[0])
    if len(matches) > 1:
        return PlaceVerdict(status="ambiguous")
    return PlaceVerdict(status="no_match")


_PLACE_PAYLOAD_KEYS: Final[tuple[str, ...]] = (
    "place_name",
    "place_wikidata_id",
    "place_description",
    "place_checked_at",
    "place_model",
    "place_resolution",
)


def _base_payload(payload: dict[str, Any]) -> dict[str, Any]:
    clean = dict(payload)
    for key in _PLACE_PAYLOAD_KEYS:
        clean[key] = None
    basis = str(clean.get("geo_basis") or "")
    has_city_point = bool(clean.get("city")) and basis in {"city", "term"}
    clean["geo_precision"] = "city" if has_city_point else ("region" if basis == "region" else None)
    clean["geo_source"] = "natural-earth" if clean["geo_precision"] else None
    return clean


def _payload_for_cache(payload: dict[str, Any], cache: PlaceLookupRow) -> dict[str, Any]:
    enriched = _base_payload(payload)
    enriched.update(
        {
            "place_checked_at": cache.checked_at.isoformat(),
            "place_model": cache.resolver_version,
            "place_resolution": cache.status,
        }
    )
    if cache.status == "resolved":
        enriched.update(
            {
                "geo_basis": "place",
                "geo_precision": cache.precision,
                "geo_source": "wikidata",
                "place_name": cache.label,
                "place_wikidata_id": cache.wikidata_id,
                "place_description": cache.description,
            }
        )
    return enriched


def _cache_is_usable(cache: PlaceLookupRow, now: datetime) -> bool:
    if cache.status == "resolved":
        return True
    checked_at = cache.checked_at
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=UTC)
    return checked_at >= now - NEGATIVE_CACHE_TTL


def _event_context(event: Event) -> PlaceContext | None:
    city = event.payload.get("city")
    if not event.country or not city or event.lat is None or event.lon is None:
        return None
    return PlaceContext(country=event.country, city=str(city), lat=event.lat, lon=event.lon)


def apply_cached_places(events: list[Event], session: Session) -> list[Event]:
    """Reapply cached truth before every RSS upsert.

    This is what makes refresh safe: unchanged text produces the same cache key
    and exact point; changed text has no matching key and the ordinary RSS
    resolver authoritatively withdraws the old point (#741).
    """
    prepared: list[tuple[Event, PlaceContext | None, PlaceCandidate | None, str | None]] = []
    keys: set[str] = set()
    for event in events:
        if not event.source.startswith("rss-") or event.category != Category.NEWS:
            prepared.append((event, None, None, None))
            continue
        context = _event_context(event)
        candidates = extract_place_candidates(event.payload, city=context.city if context else None)
        candidate = candidates[0] if context is not None and len(candidates) == 1 else None
        key = (
            lookup_key(candidate, context)
            if candidate is not None and context is not None
            else None
        )
        if key:
            keys.add(key)
        prepared.append((event, context, candidate, key))

    caches = (
        {
            row.lookup_key: row
            for row in session.execute(
                select(PlaceLookupRow).where(PlaceLookupRow.lookup_key.in_(keys))
            ).scalars()
        }
        if keys
        else {}
    )

    now = datetime.now(UTC)
    output: list[Event] = []
    for event, _context, _candidate, key in prepared:
        if not event.source.startswith("rss-") or event.category != Category.NEWS:
            output.append(event)
            continue
        cache = caches.get(key) if key else None
        if cache is not None and not _cache_is_usable(cache, now):
            cache = None
        payload = (
            _payload_for_cache(event.payload, cache) if cache else _base_payload(event.payload)
        )
        update: dict[str, Any] = {"payload": payload}
        if cache is not None and cache.status == "resolved":
            update.update({"lat": cache.lat, "lon": cache.lon})
        output.append(event.model_copy(update=update))
    return output


def _row_context(row: EventRow) -> PlaceContext | None:
    city = (row.payload or {}).get("city")
    if not row.country or not city or row.lat is None or row.lon is None:
        return None
    return PlaceContext(country=row.country, city=str(city), lat=row.lat, lon=row.lon)


def _apply_cache_to_row(row: EventRow, cache: PlaceLookupRow) -> bool:
    payload = _payload_for_cache(dict(row.payload or {}), cache)
    moved = cache.status == "resolved" and (row.lat, row.lon) != (cache.lat, cache.lon)
    if cache.status == "resolved":
        row.lat, row.lon = cache.lat, cache.lon
    row.payload = payload
    return moved


def _cache_row(
    key: str,
    candidate: PlaceCandidate,
    context: PlaceContext,
    verdict: PlaceVerdict,
    now: datetime,
) -> PlaceLookupRow:
    resolution = verdict.resolution
    return PlaceLookupRow(
        lookup_key=key,
        query_text=candidate.name,
        context_country=context.country,
        context_city=context.city,
        status=verdict.status,
        lat=resolution.lat if resolution else None,
        lon=resolution.lon if resolution else None,
        precision=resolution.precision if resolution else candidate.precision,
        wikidata_id=resolution.wikidata_id if resolution else None,
        label=resolution.label if resolution else None,
        description=resolution.description if resolution else None,
        checked_at=now,
        resolver_version=PLACE_METHOD_VERSION,
    )


def enrich_news_places(
    session: Session,
    *,
    limit: int,
    client: httpx.Client,
    now: datetime | None = None,
) -> dict[str, int]:
    """Resolve up to ``limit`` uncached names and update recent RSS rows."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    now = now or datetime.now(UTC)
    model_value = EventRow.payload["place_model"].as_string()
    rows = session.execute(
        select(EventRow)
        .where(EventRow.source.like("rss-%"))
        .where(EventRow.category == "news")
        .where(EventRow.occurred_at >= now - timedelta(days=30))
        .where(or_(model_value.is_(None), model_value != PLACE_METHOD_VERSION))
        .order_by(EventRow.occurred_at.desc())
        .limit(max(PLACE_SCAN_LIMIT, limit * 200))
    ).scalars()

    stats = {
        "scanned": 0,
        "lookups": 0,
        "cache_hits": 0,
        "enriched": 0,
        "no_candidate": 0,
        "ambiguous_text": 0,
        "no_context": 0,
        "errors": 0,
    }
    memory_cache: dict[str, PlaceLookupRow] = {}
    for row in rows:
        payload = dict(row.payload or {})
        context = _row_context(row)
        stats["scanned"] += 1
        if context is None:
            payload = _base_payload(payload)
            payload.update(
                {
                    "place_checked_at": now.isoformat(),
                    "place_model": PLACE_METHOD_VERSION,
                    "place_resolution": "no_context",
                }
            )
            row.payload = payload
            stats["no_context"] += 1
            continue

        candidates = extract_place_candidates(payload, city=context.city)
        if len(candidates) != 1:
            payload = _base_payload(payload)
            status = "no_candidate" if not candidates else "ambiguous_text"
            payload.update(
                {
                    "place_checked_at": now.isoformat(),
                    "place_model": PLACE_METHOD_VERSION,
                    "place_resolution": status,
                }
            )
            row.payload = payload
            stats[status] += 1
            continue

        candidate = candidates[0]
        key = lookup_key(candidate, context)
        cache = memory_cache.get(key) or session.get(PlaceLookupRow, key)
        if cache is not None and _cache_is_usable(cache, now):
            memory_cache[key] = cache
            stats["cache_hits"] += 1
            stats["enriched"] += int(_apply_cache_to_row(row, cache))
            continue

        if stats["lookups"] >= limit:
            # Leave unstamped. It remains eligible for the next bounded run.
            continue
        stats["lookups"] += 1
        try:
            verdict = resolve_wikidata_place(candidate, context, client=client)
        except (httpx.HTTPError, ValueError, TypeError):
            stats["errors"] += 1
            continue

        if cache is None:
            cache = _cache_row(key, candidate, context, verdict, now)
            session.add(cache)
        else:
            replacement = _cache_row(key, candidate, context, verdict, now)
            for field in (
                "status",
                "lat",
                "lon",
                "precision",
                "wikidata_id",
                "label",
                "description",
                "checked_at",
                "resolver_version",
            ):
                setattr(cache, field, getattr(replacement, field))
        memory_cache[key] = cache
        stats["enriched"] += int(_apply_cache_to_row(row, cache))
    return stats
