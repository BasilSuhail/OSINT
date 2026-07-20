"""Walk GDELT's raw export grid into daily per-country volume (#555).

The gate's narrative side reads the DOC API, which reaches back about three
months and is rate limited. This reads the raw 15-minute exports instead —
free, complete, unthrottled — and stores counts rather than rows, because raw
GDELT events are pruned at ~30 days.

Resumable: days already walked are skipped, so an interrupted run picks up
where it stopped.

    uv run python scripts/gdelt_archive.py --start 2026-04-01 --end 2026-04-07
    uv run python scripts/gdelt_archive.py --start 2026-04-01 --end 2026-04-07 --force

Cost is roughly 96 downloads per day of history. A year is ~35 k files, so
range it in chunks rather than asking for everything at once.
"""

import argparse
from datetime import date, datetime, timedelta

import httpx

from app.backtest import gdelt_archive
from app.db import session_scope
from app.sources.gdelt_fetcher import GDELT_USER_AGENT


def _parse_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=_parse_date, required=True, help="first day (YYYY-MM-DD)")
    parser.add_argument(
        "--end", type=_parse_date, required=True, help="last day, inclusive (YYYY-MM-DD)"
    )
    parser.add_argument("--concurrency", type=int, default=8, help="download threads per day")
    parser.add_argument("--force", action="store_true", help="re-walk days already ingested")
    args = parser.parse_args()

    if args.end < args.start:
        parser.error("--end is before --start")

    days = [
        args.start + timedelta(days=offset) for offset in range((args.end - args.start).days + 1)
    ]
    headers = {"User-Agent": GDELT_USER_AGENT}

    with session_scope() as session:
        already = (
            set() if args.force else gdelt_archive.ingested_days(session, args.start, args.end)
        )
        todo = [day for day in days if day not in already]
        print(f"{len(days)} day(s) in range, {len(already)} already ingested, {len(todo)} to walk.")

        with httpx.Client(timeout=60.0, headers=headers) as client:
            for day in todo:
                result = gdelt_archive.ingest_day(
                    session, day, client=client, concurrency=args.concurrency
                )
                print(
                    f"  {day.isoformat()}  files {result['files_ok']:>3d} ok / "
                    f"{result['files_missing']:>3d} missing  "
                    f"country-days {result['country_days']:>4d}",
                    flush=True,
                )


if __name__ == "__main__":
    main()
