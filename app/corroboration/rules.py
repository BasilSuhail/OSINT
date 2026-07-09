"""Sensor cross-check rules — declared, mechanical, no tuning (WS-C step 3, #361).

One rule per claim type, exactly as planned on #282: a story that *claims* a
physical event either has a matching sensor row or it doesn't. Keyword lists,
sources, window and thresholds are declared constants under METHOD_VERSION —
changing any of them is a new method version, never a silent edit.

Verdicts: ``confirmed`` / ``unconfirmed``. Not-applicable (no claim detected)
stores nothing. Confirmation requires geography — a story we cannot place gets
``unconfirmed`` with the reason recorded, because a time-only match against a
global sensor feed (quakes happen somewhere every hour) would be meaningless.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from app.enrichment.country_codes import country_name_to_iso2, iso3_to_iso2

METHOD_VERSION: str = "sensor-rules-v1.0"

#: Sensor row must sit in [story.first_seen - LOOKBACK, story.last_seen + LOOKAHEAD]:
#: the physical event precedes its coverage; the small lookahead absorbs clock skew
#: and slow sensor pipelines.
LOOKBACK_HOURS: int = 72
LOOKAHEAD_HOURS: int = 6

#: A market-crash claim needs real stress, not any market row: yfinance severity
#: is the drawdown transform (0..1), 0.5 declared a priori as "crash-consistent".
MARKET_MIN_SEVERITY: float = 0.5

#: Claim type → keywords (word-boundary matched, case-insensitive).
CLAIM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "earthquake": (
        "earthquake",
        "quake",
        "seismic",
        "tremor",
        "tremors",
        "aftershock",
        "aftershocks",
    ),
    "wildfire": (
        "wildfire",
        "wildfires",
        "forest fire",
        "forest fires",
        "bushfire",
        "bushfires",
        "brush fire",
    ),
    "disaster": (
        "flood",
        "floods",
        "flooding",
        "cyclone",
        "hurricane",
        "typhoon",
        "tsunami",
        "volcano",
        "volcanic",
        "eruption",
        "landslide",
        "mudslide",
        "storm surge",
    ),
    "market_crash": (
        "market crash",
        "market plunge",
        "market rout",
        "market meltdown",
        "stocks plunge",
        "stocks tumble",
        "stocks crash",
        "sell-off",
        "selloff",
        "bear market",
    ),
}

#: Claim type → the sensor source that can confirm it (#282 plan, verbatim).
CLAIM_SENSOR_SOURCE: dict[str, str] = {
    "earthquake": "usgs-quake",
    "wildfire": "nasa-firms",
    "disaster": "gdacs",
    "market_crash": "yfinance",
}

_CLAIM_PATTERNS: dict[str, re.Pattern[str]] = {
    claim: re.compile(r"\b(?:" + "|".join(re.escape(k) for k in kws) + r")\b")
    for claim, kws in CLAIM_KEYWORDS.items()
}


def detect_claims(titles: Iterable[str]) -> set[str]:
    """Claim types asserted anywhere in the story's member titles."""
    text = " ".join(t.lower() for t in titles if t)
    return {claim for claim, pattern in _CLAIM_PATTERNS.items() if pattern.search(text)}


def sensor_country(event: Mapping[str, Any]) -> str | None:
    """ISO2 country of a sensor row: column first, then mechanical fallbacks.

    USGS often leaves ``country`` empty (offshore epicentres) but its ``place``
    string ends in a country name; GDACS carries ``iso3`` in the payload.
    """
    if event.get("country"):
        return event["country"]
    payload = event.get("payload") or {}
    if payload.get("iso3"):
        iso2 = iso3_to_iso2(payload["iso3"])
        if iso2:
            return iso2
    place = payload.get("place")
    if place and "," in place:
        return country_name_to_iso2(place.rsplit(",", 1)[1].strip())
    return None


def evaluate_claim(
    claim: str,
    *,
    story_countries: set[str],
    window: tuple[datetime, datetime],
    sensors: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Verdict for one claim on one story. Pure — evidence in, verdict out."""
    if not story_countries:
        return {
            "verdict": "unconfirmed",
            "matched_event_id": None,
            "evidence": {"reason": "story-not-geolocated"},
        }

    start, end = window
    for event in sensors:
        if not (start <= event["occurred_at"] <= end):
            continue
        if claim == "market_crash" and (event.get("severity") or 0.0) < MARKET_MIN_SEVERITY:
            continue
        country = sensor_country(event)
        if country is None or country not in story_countries:
            continue
        evidence: dict[str, Any] = {
            "source": event["source"],
            "country": country,
            "occurred_at": event["occurred_at"].isoformat(),
        }
        if event.get("severity") is not None:
            evidence["severity"] = event["severity"]
        place = (event.get("payload") or {}).get("place")
        if place:
            evidence["place"] = place
        return {
            "verdict": "confirmed",
            "matched_event_id": event["event_id"],
            "evidence": evidence,
        }

    return {
        "verdict": "unconfirmed",
        "matched_event_id": None,
        "evidence": {"reason": "no-matching-sensor-row"},
    }
