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
RETENTION_DAYS: dict[str, int | None] = {
    "nasa-firms": 30,
    "gdelt": 90,
    "yfinance": 730,
    "fred": None,  # macro indicators — keep forever
    "usgs-quake": 365,
    "gdacs": 180,
    "eonet": 365,
    # RSS news = Layer-3 breadth. 14 d retention keeps Supabase headroom
    # while still giving the dashboard a fortnight of context.
    "rss-bbc-world": 14,
    "rss-bbc-uk": 14,
    "rss-reuters-world": 14,
    "rss-dawn": 14,
    "rss-guardian-world": 14,
    "rss-geo-english": 14,
    # UK Police data is monthly snapshots from data.police.uk. 90 d keeps
    # ~3 most-recent months on hand — enough for quarter-over-quarter
    # context without ballooning storage.
    "uk-police": 90,
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
