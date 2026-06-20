"""Historical backfill driver.

Goal: get the composite worker out of cold-start mode. With < 1 month of
ingestion every (country, month) bucket has a flat z-score → composite = 0.5
across the board. This driver pulls multi-year history for the structural
sources so the rolling-z baseline has something to compare against.

Per-source strategy
-------------------

- **yfinance**: re-runs the existing fetcher with a much larger
  ``lookback_days``. Cheap: ~10 k rows for 2 yr × 43 tickers.
- **fred**: re-runs the existing fetcher. FRED already returns full history
  per series, so a single fetch is the entire backfill.
- **gdelt**: walks the 15-minute export grid for a date range, downloading
  each zipped CSV, parsing, persisting. Idempotent on ``(source,
  source_event_id)``. Concurrency-bound. **Heavy** — 2 yr × 96 files/day ≈
  70 k downloads.

Usage
-----

::

    python -m scripts.backfill --source yfinance --years 2
    python -m scripts.backfill --source fred
    python -m scripts.backfill --source gdelt --start 2024-06-01 --end 2026-06-01 --concurrency 8

All commands are idempotent — re-run on a partial backfill picks up where it
left off.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import io
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Final

import httpx

from app.db import session_scope
from app.models import Event
from app.persistence import upsert_events
from app.sources.fred_fetcher import FredFetcher
from app.sources.gdelt_fetcher import GDELT_USER_AGENT
from app.sources.gdelt_parser import parse_csv_body
from app.sources.yfinance_fetcher import YFinanceFetcher

GDELT_EXPORT_URL: Final[str] = "http://data.gdeltproject.org/gdeltv2/{stamp}.export.CSV.zip"
GDELT_CADENCE_MINUTES: Final[int] = 15


# ---------- yfinance + fred ----------


def backfill_yfinance(years: int) -> dict[str, int]:
    """Backfill yfinance by re-running the fetcher with a large lookback."""
    fetcher = YFinanceFetcher(lookback_days=years * 365)
    events = fetcher.fetch()
    with session_scope() as session:
        inserted = upsert_events(events, session)
    return {"fetched": len(events), "inserted": inserted}


def backfill_fred() -> dict[str, int]:
    """Re-run the FRED fetcher to pull every available observation per series."""
    events = FredFetcher().fetch()
    with session_scope() as session:
        inserted = upsert_events(events, session)
    return {"fetched": len(events), "inserted": inserted}


# ---------- gdelt ----------


def _gdelt_timestamps(start: datetime, end: datetime) -> list[str]:
    """Generate every 15-min export stamp in ``[start, end)``."""
    stamps: list[str] = []
    cursor = start.replace(minute=(start.minute // 15) * 15, second=0, microsecond=0)
    step = timedelta(minutes=GDELT_CADENCE_MINUTES)
    while cursor < end:
        stamps.append(cursor.strftime("%Y%m%d%H%M%S"))
        cursor += step
    return stamps


def _download_and_parse(client: httpx.Client, stamp: str) -> list[Event]:
    """Pull one GDELT export zip + parse to events. Empty list on any error."""
    url = GDELT_EXPORT_URL.format(stamp=stamp)
    fetched_at = datetime.now(UTC)
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError:
        return []
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            if not names:
                return []
            with archive.open(names[0]) as fp:
                body = fp.read().decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        return []
    return parse_csv_body(body, fetched_at=fetched_at)


def backfill_gdelt(start: datetime, end: datetime, *, concurrency: int) -> dict[str, int]:
    """Walk the 15-min GDELT export grid in ``[start, end)`` and persist."""
    stamps = _gdelt_timestamps(start, end)
    total_fetched = 0
    total_inserted = 0
    failed_stamps = 0

    headers = {"User-Agent": GDELT_USER_AGENT}
    # One client = one connection pool across the workers.
    with httpx.Client(timeout=60.0, headers=headers) as client:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_download_and_parse, client, s): s for s in stamps}
            batch: list[Event] = []
            for future in concurrent.futures.as_completed(futures):
                stamp = futures[future]
                try:
                    events = future.result()
                except Exception:  # noqa: BLE001 - never let one bad slot kill the run
                    failed_stamps += 1
                    continue
                total_fetched += len(events)
                batch.extend(events)
                if len(batch) >= 5000:
                    with session_scope() as session:
                        total_inserted += upsert_events(events=batch, session=session)
                    batch.clear()
                if (total_fetched > 0) and (total_fetched % 50_000 < len(events)):
                    print(
                        f"  progress: {total_fetched:>8d} fetched, "
                        f"{total_inserted:>8d} inserted, "
                        f"{failed_stamps:>5d} bad slots — at stamp {stamp}",
                        flush=True,
                    )
            if batch:
                with session_scope() as session:
                    total_inserted += upsert_events(events=batch, session=session)

    return {
        "stamps": len(stamps),
        "fetched": total_fetched,
        "inserted": total_inserted,
        "failed_stamps": failed_stamps,
    }


# ---------- CLI ----------


def _parse_date(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)


def main() -> None:
    parser = argparse.ArgumentParser(description="Historical backfill driver.")
    parser.add_argument("--source", required=True, choices=["yfinance", "fred", "gdelt"])
    parser.add_argument("--years", type=int, default=2, help="yfinance lookback (default 2).")
    parser.add_argument("--start", type=_parse_date, help="gdelt range start (YYYY-MM-DD).")
    parser.add_argument("--end", type=_parse_date, help="gdelt range end (YYYY-MM-DD, exclusive).")
    parser.add_argument("--concurrency", type=int, default=8, help="gdelt download threads.")
    args = parser.parse_args()

    if args.source == "yfinance":
        result = backfill_yfinance(years=args.years)
    elif args.source == "fred":
        result = backfill_fred()
    elif args.source == "gdelt":
        if args.start is None or args.end is None:
            parser.error("--start and --end are required for --source gdelt")
        result = backfill_gdelt(args.start, args.end, concurrency=args.concurrency)
    else:
        parser.error(f"unknown source: {args.source}")
        return

    print(f"backfill ({args.source}):")
    for k, v in result.items():
        print(f"  {k:14s} {v}")


if __name__ == "__main__":
    main()
