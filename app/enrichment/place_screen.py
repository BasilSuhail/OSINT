"""What is at a point on the map (#862).

Named for the screen it fills, not for its subject: ``place.py`` beside it is
the named-place resolver that decides where a story happened, and two modules
called the same thing in one package is a trap.

Three services answer three different questions about a place, and none of
them is ours. Wikidata knows the vitals and who holds the offices, Wikipedia
knows the background, and the Planetary Computer knows what the spot looked
like the last time a satellite passed over with the sky clear enough to see
it. All three are free, none needs a key, and every one of them is somebody
else's uptime.

The vitals were meant to come from a fourth service, a country-facts API that
needed no key. Checking it against the live endpoint rather than against a
stub found it deprecated: it answers HTTP 200 with a body saying so, and its
replacement requires an API key. Wikidata already holds capital, population,
area, languages and currency, and was already being called, so the vitals moved
into that one query. One fewer dependency, and one fewer service that can
decide to start charging.

Partial failure is the normal case, not an error. Any source may go missing and
the rest still returns; the caller gets a ``degraded`` list naming the blocks
that did not answer, and the screen renders those as a quiet "unavailable"
line. Failing the whole request because one service was slow would take away
two answers to punish the absence of a third.

Nothing here is written to the database. The vitals of a country change on the
scale of years and the satellite revisits every five days, so both are held in
a small in-process cache with a time limit and forgotten on restart. A table
would buy nothing and would grow against the storage cap.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import httpx

from app.enrichment import satellite_pass
from app.enrichment.boundary import NEAR_BORDER_KM, border_distance_km, precise_country
from app.enrichment.country import country_name
from app.enrichment.satellite_pass import next_overpass

#: Per-upstream budget. Four of these run at once, so the whole call lands in
#: about this plus the point lookup.
_TIMEOUT_S = 4.0

#: A capital city does not move. The photograph is newer than that but not by
#: much: Sentinel-2 revisits every ~5 days, so a shorter limit would only buy
#: repeated identical searches.
_TEXT_TTL_S = 7 * 24 * 3600
_IMAGE_TTL_S = 12 * 3600

#: An orbit does not change during an afternoon, and the answer is only ever
#: displayed to the nearest day or hour.
_PASS_TTL_S = 6 * 3600

#: Imagery is keyed on a rounded point — two right-clicks a hundred metres
#: apart are asking about the same place and should not cost two searches.
_IMAGE_GRID = 0.05

#: Half-width of the box the photograph covers, in degrees. A Sentinel-2 tile
#: is roughly 110 km across; showing the whole thing would answer with a region
#: when the reader asked about a point.
_BOX_DEGREES = 0.05

#: Above this the scene is more cloud than ground. The percentage that survives
#: is printed on the screen, because a half-white square with no explanation
#: reads as a broken image rather than as weather.
_MAX_CLOUD_PCT = 40

#: Wikipedia and Wikidata both ask callers to identify themselves and answer
#: 403 to those that do not.
_USER_AGENT = "OSINT-console/1.0 (https://github.com/BasilSuhail/OSINT)"

_STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
_IMAGE_URL = (
    "https://planetarycomputer.microsoft.com/api/data/v1/item/"
    "bbox/{minx},{miny},{maxx},{maxy}/512x512.png"
    "?collection=sentinel-2-l2a&item={item}&assets=visual"
    "&asset_bidx=visual%7C1%2C2%2C3&nodata=0"
)
_FULL_IMAGE_URL = (
    "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png"
    "?collection=sentinel-2-l2a&item={item}&assets=visual"
    "&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png"
)

#: Labels are joined explicitly rather than through ``wikibase:label``. The two
#: cannot be mixed: the label service overwrites a variable an explicit join
#: has already bound, and the symptom is a screen showing an entity id where a
#: currency should be.
#:
#: Currency prefers its ISO 4217 code over its label, because at least one
#: major currency has no English label in the query service's graph at all —
#: and a three-letter code reads better on a narrow screen than a long name.
#:
#: Aggregating is what makes the row singular. Grouping on the plain values
#: instead splits a country with two currencies or several census figures
#: across several rows, and taking the first one then silently drops half the
#: answer.
_SPARQL = """
SELECT (SAMPLE(?govLabel) AS ?government) (SAMPLE(?hosLabel) AS ?headOfState)
       (SAMPLE(?hogLabel) AS ?headOfGovernment) (SAMPLE(?capLabel) AS ?capital)
       (MAX(?pop) AS ?population) (MAX(?areaValue) AS ?area)
       (GROUP_CONCAT(DISTINCT ?langLabel; separator="|") AS ?languages)
       (GROUP_CONCAT(DISTINCT ?curName; separator="|") AS ?currencies)
WHERE {
  ?country wdt:P297 "%s".
  OPTIONAL { ?country wdt:P122 ?gov.  ?gov  rdfs:label ?govLabel.  FILTER(lang(?govLabel)="en") }
  OPTIONAL { ?country wdt:P35  ?hos.  ?hos  rdfs:label ?hosLabel.  FILTER(lang(?hosLabel)="en") }
  OPTIONAL { ?country wdt:P6   ?hog.  ?hog  rdfs:label ?hogLabel.  FILTER(lang(?hogLabel)="en") }
  OPTIONAL { ?country wdt:P36  ?cap.  ?cap  rdfs:label ?capLabel.  FILTER(lang(?capLabel)="en") }
  OPTIONAL { ?country wdt:P37  ?lang. ?lang rdfs:label ?langLabel. FILTER(lang(?langLabel)="en") }
  OPTIONAL {
    ?country wdt:P38 ?cur.
    OPTIONAL { ?cur wdt:P498 ?curCode. }
    OPTIONAL { ?cur rdfs:label ?curLabel. FILTER(lang(?curLabel)="en") }
    BIND(COALESCE(?curCode, ?curLabel) AS ?curName)
  }
  OPTIONAL { ?country wdt:P1082 ?pop. }
  OPTIONAL { ?country wdt:P2046 ?areaValue. }
}
GROUP BY ?country
LIMIT 1
"""

_cache: dict[str, tuple[float, Any]] = {}


def clear_caches() -> None:
    """Forget everything held in memory. Tests need this; nothing else does."""
    _cache.clear()
    precise_country.cache_clear()
    border_distance_km.cache_clear()
    satellite_pass.clear_cache()


def _cached(key: str, ttl: float, produce: Callable[[], Any]) -> Any:
    hit = _cache.get(key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < ttl:
        return hit[1]
    value = produce()
    _cache[key] = (now, value)
    return value


def _new_client() -> httpx.Client:
    return httpx.Client(
        timeout=_TIMEOUT_S, headers={"User-Agent": _USER_AGENT}, follow_redirects=True
    )


def _number(raw: str | None) -> float | int | None:
    """Wikidata returns quantities as strings; a population is not a string."""
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


def _facts(client: httpx.Client, iso: str) -> dict:
    """Vitals and offices, in one query.

    Returns both screen blocks together because they come from one request:
    when the service is down, both are missing, and saying so twice is more
    honest than pretending they were asked for separately.
    """
    response = client.get(
        "https://query.wikidata.org/sparql",
        params={"query": _SPARQL % iso, "format": "json"},
    )
    response.raise_for_status()
    bindings = (response.json().get("results") or {}).get("bindings") or []
    if not bindings:
        raise LookupError(f"no country in the knowledge base for {iso}")
    row = bindings[0]

    def value(field: str) -> str | None:
        return (row.get(field) or {}).get("value") or None

    def split(field: str) -> list[str]:
        raw = value(field)
        return sorted(part for part in (raw or "").split("|") if part)

    return {
        "profile": {
            "capital": value("capital"),
            "population": _number(value("population")),
            "area_km2": _number(value("area")),
            "languages": split("languages"),
            "currencies": split("currencies"),
        },
        "government": {
            "type": value("government"),
            "head_of_state": value("headOfState"),
            "head_of_government": value("headOfGovernment"),
            "as_of": datetime.now(UTC).date().isoformat(),
        },
    }


def _summary(client: httpx.Client, title: str) -> dict:
    """Two sentences of background, and where to read the rest."""
    response = client.get(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}",
    )
    response.raise_for_status()
    row = response.json()
    return {
        "title": row.get("title"),
        "extract": row.get("extract"),
        "url": ((row.get("content_urls") or {}).get("desktop") or {}).get("page"),
        "thumbnail": (row.get("thumbnail") or {}).get("source"),
    }


def _imagery(client: httpx.Client, lat: float, lon: float) -> dict:
    """The newest Sentinel-2 scene over this point with the sky clear enough.

    The URL returned is a crop of the scene around the point, not the scene's
    own footprint, so the picture answers about a place rather than a region.
    """
    response = client.post(
        _STAC_SEARCH,
        json={
            "collections": ["sentinel-2-l2a"],
            "intersects": {"type": "Point", "coordinates": [lon, lat]},
            "query": {"eo:cloud_cover": {"lt": _MAX_CLOUD_PCT}},
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
            "limit": 1,
        },
    )
    response.raise_for_status()
    features = response.json().get("features") or []
    if not features:
        raise LookupError("no recent low-cloud scene over this point")
    item = features[0]
    properties = item.get("properties") or {}
    return {
        "url": _IMAGE_URL.format(
            minx=round(lon - _BOX_DEGREES, 4),
            miny=round(lat - _BOX_DEGREES, 4),
            maxx=round(lon + _BOX_DEGREES, 4),
            maxy=round(lat + _BOX_DEGREES, 4),
            item=item.get("id"),
        ),
        "full_url": _FULL_IMAGE_URL.format(item=item.get("id")),
        "captured_at": properties.get("datetime"),
        "cloud_cover_pct": properties.get("eo:cloud_cover"),
        "item_id": item.get("id"),
    }


def _country_block(lat: float, lon: float, iso: str) -> dict:
    distance = border_distance_km(lat, lon, iso)
    return {
        "iso2": iso,
        "name": country_name(iso) or iso,
        "border_distance_km": None if distance is None else round(distance, 1),
        "near_border": distance is not None and distance < NEAR_BORDER_KM,
    }


def _gather(
    jobs: dict[str, Callable[[], Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Run every job at once; a job that raises loses its block, not the rest."""
    blocks: dict[str, Any] = {}
    degraded: list[str] = []
    if not jobs:
        return blocks, degraded
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {name: pool.submit(job) for name, job in jobs.items()}
        for name, future in futures.items():
            try:
                blocks[name] = future.result()
            except Exception:
                blocks[name] = None
                degraded.append(name)
    return blocks, degraded


def _assemble(
    *,
    iso: str | None,
    country: dict | None,
    point: dict | None,
    client: httpx.Client | None,
) -> dict:
    owned = client is None
    http = client or _new_client()
    try:
        jobs: dict[str, Callable[[], Any]] = {}
        if iso:
            name = country_name(iso) or iso
            jobs["facts"] = lambda: _cached(f"facts:{iso}", _TEXT_TTL_S, lambda: _facts(http, iso))
            jobs["summary"] = lambda: _cached(
                f"summary:{iso}", _TEXT_TTL_S, lambda: _summary(http, name)
            )
        if point is not None:
            lat, lon = point["lat"], point["lon"]
            key = f"imagery:{round(lat / _IMAGE_GRID)}:{round(lon / _IMAGE_GRID)}"
            jobs["imagery"] = lambda: _cached(key, _IMAGE_TTL_S, lambda: _imagery(http, lat, lon))
            #: Why the photograph is as old as it is (#876). Its own block, so
            #: a slow element fetch cannot take the picture down with it.
            pass_key = f"pass:{round(lat / _IMAGE_GRID)}:{round(lon / _IMAGE_GRID)}"
            jobs["next_pass"] = lambda: _cached(
                pass_key, _PASS_TTL_S, lambda: next_overpass(lat, lon, client=http)
            )

        blocks, degraded = _gather(jobs)

        #: One request fills two screen blocks, so both go missing together and
        #: both are named. The screen draws a section per block and has to know
        #: which of its sections have nothing behind them.
        facts = blocks.get("facts")
        if "facts" in degraded:
            degraded.remove("facts")
            degraded.extend(["profile", "government"])
        if not iso:
            # Open water has no government and no capital. Those blocks are
            # named as missing rather than silently absent, so the screen can
            # say why there is nothing there.
            degraded.extend(["profile", "government", "summary"])
        return {
            "point": point,
            "country": country,
            "profile": (facts or {}).get("profile"),
            "government": (facts or {}).get("government"),
            "summary": blocks.get("summary"),
            "imagery": blocks.get("imagery"),
            "next_pass": blocks.get("next_pass"),
            "degraded": degraded,
        }
    finally:
        if owned:
            http.close()


def describe_place(lat: float, lon: float, *, client: httpx.Client | None = None) -> dict:
    """Everything known about the point that was right-clicked."""
    iso = precise_country(lat, lon)
    return _assemble(
        iso=iso,
        country=_country_block(lat, lon, iso) if iso else None,
        point={"lat": lat, "lon": lon},
        client=client,
    )


def describe_place_by_country(iso: str, *, client: httpx.Client | None = None) -> dict:
    """The same screen, reached from a country code with no point behind it.

    There is no photograph here and no pretence of one. Inventing a coordinate
    from a centroid would put a picture of a field on the screen and imply
    somebody chose it.
    """
    code = iso.upper()
    return _assemble(
        iso=code,
        country={
            "iso2": code,
            "name": country_name(code) or code,
            "border_distance_km": None,
            "near_border": False,
        },
        point=None,
        client=client,
    )
