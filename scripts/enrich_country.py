"""Backfill `events.country` for existing rows using the offline lookup.

Usage:
    python -m scripts.enrich_country [--batch-size 1000] [--sources nasa-firms,usgs-quake]

Streams batches of rows with country IS NULL and a non-null lat/lon, runs them
through `app.enrichment.country.country_for`, and updates in place. Idempotent
— re-running picks up only still-null rows.

Prints progress + a final breakdown of {source: rows_tagged, rows_unmapped}.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import session_scope
from app.db_models import EventRow
from app.enrichment.country import country_for


def _stream_batches(session: Session, batch_size: int, sources: Iterable[str] | None):
    """Yield batches of EventRow ids + lat/lon needing enrichment."""
    last_id = 0
    while True:
        stmt = (
            select(EventRow.id, EventRow.source, EventRow.lat, EventRow.lon)
            .where(
                EventRow.country.is_(None),
                EventRow.lat.is_not(None),
                EventRow.lon.is_not(None),
                EventRow.id > last_id,
            )
            .order_by(EventRow.id)
            .limit(batch_size)
        )
        if sources:
            stmt = stmt.where(EventRow.source.in_(list(sources)))
        rows = session.execute(stmt).all()
        if not rows:
            return
        yield rows
        last_id = rows[-1].id


def run(batch_size: int = 1000, sources: Iterable[str] | None = None) -> dict[str, dict[str, int]]:
    """Run the backfill. Returns per-source { tagged, unmapped } counts."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tagged": 0, "unmapped": 0})
    total = 0
    with session_scope() as session:
        for batch in _stream_batches(session, batch_size, sources):
            updates: list[tuple[int, str]] = []
            for row in batch:
                iso = country_for(row.lat, row.lon)
                if iso is None:
                    counts[row.source]["unmapped"] += 1
                    continue
                updates.append((row.id, iso))
                counts[row.source]["tagged"] += 1
            if updates:
                # Group ids by the iso they're being tagged with → one UPDATE
                # statement per ISO with a WHERE id IN (…). Per-id UPDATEs hit
                # the database's per-statement timeout once the backlog is large.
                by_iso: dict[str, list[int]] = defaultdict(list)
                for event_id, iso in updates:
                    by_iso[iso].append(event_id)
                for iso, ids in by_iso.items():
                    # Chunk to stay well under Postgres' 65 535 bound-param cap.
                    for start in range(0, len(ids), 5000):
                        chunk = ids[start : start + 5000]
                        session.execute(
                            update(EventRow).where(EventRow.id.in_(chunk)).values(country=iso)
                        )
                session.commit()
            total += len(batch)
            print(f"processed {total:>8d} rows...", flush=True)

    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill events.country via polygon lookup.")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument(
        "--sources",
        type=str,
        default=None,
        help="Comma-separated list of source slugs (default: all).",
    )
    args = parser.parse_args()
    sources = args.sources.split(",") if args.sources else None
    counts = run(batch_size=args.batch_size, sources=sources)
    print("\nBackfill summary:")
    for source, breakdown in sorted(counts.items()):
        print(
            f"  {source:14s} tagged={breakdown['tagged']:>6d}  unmapped={breakdown['unmapped']:>6d}"
        )


if __name__ == "__main__":
    main()
