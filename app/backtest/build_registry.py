"""Build a real event registry for the lead-time gate (#518).

`events.yaml` shipped with a single entry whose own note called it a "frozen
starter event for backtest smoke run". The gate's pass bar is "median lead ≥ 1
day AND more than half of events leading", which at n=1 is a coin toss, so no
verdict it produced could mean anything.

Anchors come from USGS: significant earthquakes have an unambiguous date, an
unambiguous location, and no dependence on how anyone reported them — which is
the point, since the claim under test is whether reporting lags the sensor.

The registry stays a frozen, hashed artifact. This module writes it once; the
gate reads it and refuses to run if it has been edited since (see
`registry.load_registry`). Regenerating deliberately produces a new hash, so a
changed sample can never be confused with a changed result.
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.enrichment.country import country_from_text

_USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
_TIMEOUT_S = 60.0

#: Magnitude floor for an anchor. Below roughly M6 a quake is often not reported
#: internationally at all, so "the narrative never spiked" would say more about
#: newsworthiness than about lead time.
DEFAULT_MIN_MAGNITUDE = 6.0

#: Days between anchors in the same country. Two shocks a week apart share their
#: 60-day windows, so the second is not an independent test of the same claim.
MIN_SEPARATION_DAYS = 30


def select_anchors(
    features: list[dict[str, Any]],
    *,
    min_separation_days: int = MIN_SEPARATION_DAYS,
) -> list[dict[str, Any]]:
    """Pick independent, country-attributable anchors, newest first.

    Drops quakes at sea: without a country there is no national news volume to
    compare against, so the divergence question is not even askable.
    """
    chosen: list[dict[str, Any]] = []
    last_by_country: dict[str, date] = {}
    for feature in features:
        props = feature.get("properties") or {}
        place = str(props.get("place") or "")
        country = country_from_text(place)
        if not country:
            continue
        millis = props.get("time")
        if not isinstance(millis, (int, float)):
            continue
        day = datetime.fromtimestamp(millis / 1000, tz=UTC).date()
        previous = last_by_country.get(country)
        if previous is not None and abs((previous - day).days) < min_separation_days:
            continue
        last_by_country[country] = day
        magnitude = props.get("mag")
        chosen.append(
            {
                "id": f"{country.lower()}-{day:%Y%m%d}-m{magnitude}",
                "country": country,
                "date": day,
                "domain": "hazard",
                "topic": "earthquake",
                "source_url": props.get("url") or _USGS_URL,
                "notes": f"M{magnitude} {place}",
            }
        )
    return chosen


def fetch_significant(start: date, end: date, *, min_magnitude: float) -> list[dict[str, Any]]:
    response = httpx.get(
        _USGS_URL,
        params={
            "format": "geojson",
            "starttime": start.isoformat(),
            "endtime": end.isoformat(),
            "minmagnitude": min_magnitude,
            "orderby": "time",
        },
        timeout=_TIMEOUT_S,
    )
    response.raise_for_status()
    return response.json().get("features") or []


def render_registry(events: list[dict[str, Any]]) -> str:
    return yaml.safe_dump({"events": events}, sort_keys=False, allow_unicode=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the backtest event registry")
    parser.add_argument("--days", type=int, default=120, help="lookback window in days")
    parser.add_argument("--min-magnitude", type=float, default=DEFAULT_MIN_MAGNITUDE)
    parser.add_argument("--out", default="app/backtest/events.yaml")
    args = parser.parse_args()

    end = datetime.now(UTC).date()
    start = end - timedelta(days=args.days)
    features = fetch_significant(start, end, min_magnitude=args.min_magnitude)
    events = select_anchors(features)
    Path(args.out).write_text(render_registry(events))
    print(f"wrote {len(events)} anchors to {args.out} ({start}..{end}, M>={args.min_magnitude})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
