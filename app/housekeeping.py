"""Retention policy + housekeeping for the events table.

Different sources have different retention needs:

- NASA FIRMS dumps ~35 k rows/day. Without pruning the table balloons past
  Supabase's free-tier ceiling inside a fortnight. 30 days of fire history is
  plenty for the hazard rolling-z baseline, so we prune aggressively.
- GDELT is denser but the geopolitical signal benefits from longer history.
- yfinance + FRED are tiny — never delete.

The `housekeeping_runs` table audits each prune cycle. See
``docs/architecture/04-schema.md`` for the table definition.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db_models import EventRow, HousekeepingRunRow

#: Per-source retention windows in days. ``None`` means "never delete" (keep
#: forever — used for low-volume series whose history is irreplaceable).
# Storage budget while we're on Supabase free tier (#106 + #156): prune
# every high-volume source to 3 d so we have room to add the
# source-expansion batch without breaking the free-tier ceiling. When the
# project moves off Supabase to local HDDs the policy flips back to
# keep-everything — but until then, only macro / market series with
# irreplaceable history are exempt.
RETENTION_DAYS: dict[str, int | None] = {
    # News = nobody wants yesterday's headlines. 1 d window matches
    # what you'd actually read on the dashboard.
    "rss-bbc-world": 1,
    "rss-bbc-uk": 1,
    "rss-reuters-world": 1,
    "rss-dawn": 1,
    "rss-guardian-world": 1,
    "rss-geo-english": 1,
    # Hazard + geopolitical = only "live" matters analytically. 2 d
    # gives the convergence detector enough overlap to see today's
    # rising cluster.
    "nasa-firms": 2,
    "usgs-quake": 2,
    "gdacs": 2,
    "eonet": 2,
    "gdelt": 2,
    # UK Police = monthly batch ingest, low row volume. 7 d keeps the
    # latest monthly drop in the buffer even on the slowest tick.
    "uk-police": 7,
    # Market / macro = low volume + trend context matters. yfinance
    # daily prices for 30 d enables a clean weekly chart; FRED keeps
    # forever because the macro series are irreplaceable.
    "yfinance": 30,
    "fred": None,
}


def _prune_source(session: Session, *, source: str, days: int, now: datetime) -> int:
    """Delete events for ``source`` older than ``days``. Returns rows deleted."""
    cutoff = now - timedelta(days=days)
    result = session.execute(
        delete(EventRow).where(
            EventRow.source == source,
            EventRow.occurred_at < cutoff,
        )
    )
    return result.rowcount or 0


def prune_events(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Run one full retention pass across every configured source.

    Returns ``{source: rows_deleted}`` for the caller to log. The audit row in
    ``housekeeping_runs`` is also written.
    """
    started_at = time.monotonic()
    now = now or datetime.now(UTC)

    deleted_by_source: dict[str, int] = {}
    for source, days in RETENTION_DAYS.items():
        if days is None:
            deleted_by_source[source] = 0
            continue
        deleted_by_source[source] = _prune_source(session, source=source, days=days, now=now)

    total_deleted = sum(deleted_by_source.values())
    duration_ms = int((time.monotonic() - started_at) * 1000)
    notes_lines = [f"{src}: {n}" for src, n in deleted_by_source.items() if n]
    notes = "; ".join(notes_lines) if notes_lines else None
    session.add(
        HousekeepingRunRow(
            job_name="events-retention",
            archived_count=0,  # Parquet archival lands in a follow-up.
            deleted_count=total_deleted,
            duration_ms=duration_ms,
            notes=notes,
        )
    )
    return deleted_by_source
