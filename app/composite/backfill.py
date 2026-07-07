"""Historical signal backfill — market + geopolitical + hazard → composite scores.

Builds historical events IN MEMORY (they never touch the events table, so
retention pruning cannot eat them) and feeds them through the exact live
composite pipeline: aggregate → rolling z-score → sigmoid score → scores
upsert. Same functions, same method version — the methodology is identical
to live by construction; components carry `backfill: true` for provenance.

The geopolitical domain comes from GDELT (see app/composite/gdelt.py), the
pre-registered B3 source — never ACLED, which is the ground-truth side of
the evaluation (same source on both sides = circular). The GDELT download
is checkpointed per month under $OSINT_DATA_DIR/gdelt/, so an interrupted
first run resumes for free and later runs read from cache.

Usage:
    python -m app.composite.backfill      # warmup 2014-01, scores 2015-01 → 2024-12
    make backfill-signals
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import yfinance as yf
from httpx import Client
from sqlalchemy.orm import Session

from app.composite.aggregation import aggregate_events_to_domain_signals
from app.composite.config import DEFAULT_METHOD_VERSION
from app.composite.gdelt import fetch_gdelt_history
from app.composite.normalization import normalize_domain_signals
from app.composite.persistence import upsert_scores
from app.composite.scoring import compute_scores
from app.db import session_scope
from app.sources.usgs_quake_fetcher import parse_geojson_body
from app.sources.yfinance_fetcher import COUNTRY_ETFS, _compute_events

#: Minimum magnitude for historical quakes. Global M4.5+ runs ~7-8k rows/year,
#: comfortably under the FDSN 20k per-query cap with yearly chunks.
USGS_MIN_MAGNITUDE: float = 4.5

_USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

#: (start, end) → list of event dicts with country/category/severity/occurred_at.
FetchFn = Callable[[date, date], list[dict[str, Any]]]

WARMUP_START = date(2014, 1, 1)
SCORES_START = date(2015, 1, 1)
END = date(2024, 12, 31)


def iter_year_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end] into calendar-year chunks, inclusive edges."""
    if end < start:
        raise ValueError("end must not precede start")
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        year_end = date(cursor.year, 12, 31)
        chunks.append((cursor, min(year_end, end)))
        cursor = date(cursor.year + 1, 1, 1)
    return chunks


def fetch_market_history(start: date, end: date) -> list[dict[str, Any]]:
    """Daily country-ETF history → market event dicts, one per trading day.

    Reuses the live fetcher's drawdown → severity transform so historical and
    live market severities are computed identically.
    """
    fetched_at = datetime.now(UTC)
    events: list[dict[str, Any]] = []
    for country, ticker in COUNTRY_ETFS.items():
        history = yf.Ticker(ticker).history(
            start=start.isoformat(), end=end.isoformat(), interval="1d", auto_adjust=True
        )
        if history.empty:
            continue
        for event in _compute_events(
            history,
            country=country,
            ticker=ticker,
            fetched_at=fetched_at,
            lookback_days=len(history),
        ):
            events.append(
                {
                    "country": event.country,
                    "category": str(event.category),
                    "severity": event.severity,
                    "occurred_at": event.occurred_at,
                }
            )
    return events


def fetch_hazard_history(start: date, end: date) -> list[dict[str, Any]]:
    """Historical USGS quakes (M ≥ USGS_MIN_MAGNITUDE) in yearly chunks.

    A failed chunk raises — silently writing a partial year would skew that
    year's hazard baseline for every country.
    """
    fetched_at = datetime.now(UTC)
    events: list[dict[str, Any]] = []
    with Client(timeout=60.0) as client:
        for chunk_start, chunk_end in iter_year_chunks(start, end):
            response = client.get(
                _USGS_URL,
                params={
                    "format": "geojson",
                    "starttime": chunk_start.isoformat(),
                    "endtime": chunk_end.isoformat(),
                    "minmagnitude": str(USGS_MIN_MAGNITUDE),
                },
            )
            response.raise_for_status()
            for event in parse_geojson_body(response.text, fetched_at=fetched_at):
                if event.country is None or event.severity is None:
                    continue
                events.append(
                    {
                        "country": event.country,
                        "category": str(event.category),
                        "severity": event.severity,
                        "occurred_at": event.occurred_at,
                    }
                )
    return events


def fetch_geopolitical_history(start: date, end: date) -> list[dict[str, Any]]:
    """GDELT monthly mean-Goldstein events (checkpoint-cached, resumable)."""
    return fetch_gdelt_history(start, end)


def run_signal_backfill(
    *,
    warmup_start: date = WARMUP_START,
    scores_start: date = SCORES_START,
    end: date = END,
    market_fetch: FetchFn = fetch_market_history,
    geopolitical_fetch: FetchFn = fetch_geopolitical_history,
    hazard_fetch: FetchFn = fetch_hazard_history,
    session: Session,
) -> dict[str, Any]:
    """Fetch all three domains, run the live pipeline, upsert scores in-window."""
    events = (
        market_fetch(warmup_start, end)
        + geopolitical_fetch(warmup_start, end)
        + hazard_fetch(warmup_start, end)
    )

    aggregated = aggregate_events_to_domain_signals(events)
    normalized = normalize_domain_signals(aggregated)
    scores = compute_scores(normalized, method_version=DEFAULT_METHOD_VERSION)

    window_start = datetime(scores_start.year, scores_start.month, 1, tzinfo=UTC)
    window_end = datetime(end.year, end.month, 1, tzinfo=UTC)
    in_window = []
    for score in scores:
        if window_start <= score.bucket_start <= window_end:
            score.components["backfill"] = True
            in_window.append(score)

    upserted = upsert_scores(in_window, session)
    return {
        "events_fetched": len(events),
        "buckets_aggregated": len(aggregated),
        "scores_written": len(in_window),
        "rows_upserted": upserted,
        "method_version": DEFAULT_METHOD_VERSION,
    }


def main() -> int:
    with session_scope() as session:
        result = run_signal_backfill(session=session)
    print(
        f"signal backfill {result['method_version']} — "
        f"{result['scores_written']} scores written "
        f"({result['events_fetched']} events fetched, "
        f"{result['buckets_aggregated']} buckets)"
    )
    if result["scores_written"] == 0:
        print("warning: nothing written — check network access to yfinance/USGS", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
