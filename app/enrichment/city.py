"""Headline / summary → city pinpoint.

Used by the RSS news fetchers so each news event lands on a real city pin
rather than at the country centroid. Pure offline lookup against a bundled
Natural Earth 50m populated-places table (~1.2 k cities, ~100 KB JSON,
sorted by population so the first match favours the major city when names
collide).

Why this exists: BBC UK + Dawn + Geo etc. don't carry lat/lon on their
RSS items. Without this, every UK headline would render at the UK
centroid and every Pakistan headline at the Pakistan centroid → blob
rather than a map of stories. See GitHub issue #112.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).parent / "data" / "cities.json"


@dataclass(frozen=True)
class CityHit:
    name: str
    iso: str
    lat: float
    lon: float


def _load_cities() -> list[dict]:
    with _DATA_PATH.open() as fh:
        return json.load(fh)


_CITIES_RAW = _load_cities()


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation that breaks word boundaries."""
    return re.sub(r"[^\w\s]", " ", text.lower())


def _build_index() -> dict[str, list[dict]]:
    """Lowercase name → list of city records (deduped, population-sorted).

    A single name may map to multiple cities (Cambridge UK vs Cambridge MA);
    we keep the list ordered by population so a default match without a
    country bias returns the bigger one.
    """
    idx: dict[str, list[dict]] = {}
    for c in _CITIES_RAW:
        keys = {c["n"].lower()}
        for alt in c.get("alt", []) or []:
            keys.add(alt.lower())
        for k in keys:
            if len(k) < 3:
                # Filter junk like 'Ur' / 'Ho' so the regex engine doesn't
                # match prepositions in headlines.
                continue
            idx.setdefault(k, []).append(c)
    return idx


_INDEX = _build_index()
_SORTED_NAMES = sorted(_INDEX.keys(), key=len, reverse=True)


@lru_cache(maxsize=8192)
def city_for(
    text: str,
    country_hint: str | None = None,
) -> CityHit | None:
    """Find the most likely city mentioned in ``text``.

    Strategy:
    1. Substring-scan a tokenised lowercase version against the bundled name
       index. Longer names first so 'New York' beats 'York' when both match.
    2. If multiple candidates collide on the same name, prefer the one
       whose ISO matches ``country_hint`` (e.g. BBC UK feed → prefer GB).
    3. Otherwise fall back to the largest by population.

    Returns None if no city name is recognised.
    """
    if not text:
        return None
    haystack = " " + _normalise(text) + " "
    hint = country_hint.upper() if country_hint else None

    matches: list[dict] = []
    for name in _SORTED_NAMES:
        # Word-boundary check via padded haystack lookup.
        needle = " " + name + " "
        if needle in haystack:
            for c in _INDEX.get(name) or []:
                matches.append(c)
        if len(matches) >= 12:
            break  # plenty of candidates; longest match heuristic + hint will sort it.

    if not matches:
        return None

    # If we have a country hint and any candidate lives in that country,
    # prefer it. This breaks ties like 'Newcastle' (UK feed + AU city) or
    # 'East London' (UK feed + ZA city) so the feed's regional bias wins.
    if hint:
        hinted = [c for c in matches if c["iso"] == hint]
        if hinted:
            chosen = max(hinted, key=lambda c: c.get("pop", 0))
            return CityHit(
                name=chosen["n"], iso=chosen["iso"], lat=chosen["lat"], lon=chosen["lon"]
            )

    # No country hint or no hinted match — fall back to the largest by pop.
    chosen = max(matches, key=lambda c: c.get("pop", 0))
    return CityHit(name=chosen["n"], iso=chosen["iso"], lat=chosen["lat"], lon=chosen["lon"])
