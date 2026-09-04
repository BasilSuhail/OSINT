"""Restore the true onset on GDACS rows stamped at fetch time.

Every active GDACS event used to be written with `occurred_at` set to the
moment it was fetched, which restamped a point-in-time hazard on each poll that
still found it in the feed. An earthquake listed at 20 Aug 10:08 UTC was stored
as 24 Aug 10:49 and read on the map as having happened four days after it did.

The fetcher now stores `fromdate`. Rows written before that keep the wrong
date, and with the time-based retention window switched off on a board they
keep it indefinitely — there is no prune coming to clear them. The onset was
always preserved in `payload.from_date`, so the repair is local: no re-fetch,
and nothing asked of GDACS.

Only rows that actually disagree are rewritten, and only where the payload
carries a parseable onset. A row whose stored date already matches its onset is
left alone rather than rewritten to the same value, so `updated_at` does not
move for rows that were never wrong — the map polls that column to pull revised
rows to open consoles, and touching every row would send all of them.

Usage:
    .venv/bin/python -m scripts.backfill_gdacs_onset [--dry-run] [--batch-size 500]
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.db_models import EventRow

SOURCE = "gdacs"


def parse_onset(raw: object) -> datetime | None:
    """`payload.from_date` as an aware datetime, or None if unusable."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def run(session: Session, *, batch_size: int, dry_run: bool) -> dict[str, int]:
    counts = {"scanned": 0, "repaired": 0, "already_correct": 0, "no_onset": 0}
    offset = 0
    while True:
        rows = (
            session.execute(
                select(EventRow)
                .where(EventRow.source == SOURCE)
                .order_by(EventRow.id)
                .offset(offset)
                .limit(batch_size)
            )
            .scalars()
            .all()
        )
        if not rows:
            break
        offset += len(rows)
        for row in rows:
            counts["scanned"] += 1
            payload = row.payload if isinstance(row.payload, dict) else {}
            onset = parse_onset(payload.get("from_date"))
            if onset is None:
                counts["no_onset"] += 1
                continue
            stored = row.occurred_at
            if stored is not None and stored.tzinfo is None:
                stored = stored.replace(tzinfo=UTC)
            if stored == onset:
                counts["already_correct"] += 1
                continue
            counts["repaired"] += 1
            if not dry_run:
                row.occurred_at = onset
        if not dry_run:
            session.commit()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    args = parser.parse_args()

    with session_scope() as session:
        counts = run(session, batch_size=args.batch_size, dry_run=args.dry_run)
    for key in sorted(counts):
        print(f"{key:18} {counts[key]:,}")


if __name__ == "__main__":
    main()
