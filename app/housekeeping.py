"""Retention policy + housekeeping for the events table.

Different sources have different retention needs:

- NASA FIRMS dumps ~35 k rows/day. Without pruning the table balloons past
  the local disk budget inside a fortnight. 30 days of fire history is
  plenty for the hazard rolling-z baseline, so we prune aggressively.
- GDELT is denser but the geopolitical signal benefits from longer history.
- yfinance + FRED are tiny — never delete.

The `housekeeping_runs` table audits each prune cycle. See
``docs/architecture/04-schema.md`` for the table definition.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db_models import EventRow, HousekeepingRunRow
from app.settings import settings

def retention_days() -> dict[str, int | None]:
    """Per-source retention windows (days). ``None`` = never delete.

    High-volume sources are pruned to a few days to keep the local disk
    budget small (GDELT is the largest table). News/hazard/GDELT windows are
    env-overridable via RETENTION_*_DAYS; market/macro history is irreplaceable
    so it is exempt.
    """
    news = settings.retention_news_days
    hazard = settings.retention_hazard_days
    return {
        "rss-bbc-world": news,
        "rss-bbc-uk": news,
        "rss-reuters-world": news,
        "rss-dawn": news,
        "rss-guardian-world": news,
        "rss-geo-english": news,
        "nasa-firms": hazard,
        "usgs-quake": hazard,
        "gdacs": hazard,
        "eonet": hazard,
        "gdelt": settings.retention_gdelt_days,
        "opensky-adsb": hazard,
        "abuse-ch-urlhaus": hazard,
        "abuse-ch-feodo": hazard,
        "polymarket": hazard,
        "uk-police": 7,
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
    policy = retention_days()
    for source, days in policy.items():
        if days is None:
            deleted_by_source[source] = 0
            continue
        deleted_by_source[source] = _prune_source(session, source=source, days=days, now=now)

    # Generic RSS prefix rule: any rss-* source not explicitly listed in
    # the retention policy gets the configured news window — matches the explicit
    # entries above + the dashboard time-range picker's max.
    explicit = set(policy)
    seen_rss = session.execute(
        select(EventRow.source).where(EventRow.source.like("rss-%")).distinct()
    )
    for (src,) in seen_rss:
        if src in explicit:
            continue
        deleted_by_source[src] = _prune_source(session, source=src, days=settings.retention_news_days, now=now)

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
