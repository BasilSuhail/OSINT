"""Retention policy + housekeeping for the events table.

Two rules keep the database bounded on a small disk (issue #353):

1. **Time** — keep ~30 days of events per source (env-overridable via
   ``RETENTION_*_DAYS``); FRED/EM-DAT are irreplaceable and never deleted.
2. **Size** — if the database's disk footprint exceeds ``STORAGE_CAP_GB``,
   trim the oldest whole event-days until the overage is covered
   (``enforce_size_cap``). OpenSky ADS-B alone writes ~1 M rows/day, so this
   is the guardrail against any source outrunning the time windows.

The `housekeeping_runs` table audits each prune cycle. See
``docs/architecture/04-schema.md`` for the table definition.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.db_models import BrainNarrativeRow, EventRow, HousekeepingRunRow
from app.settings import settings

logger = logging.getLogger(__name__)


def retention_days() -> dict[str, int | None]:
    """Per-source retention windows (days). ``None`` = never delete.

    Default is ~30 days everywhere. News/hazard/GDELT windows are
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
        "acled": settings.retention_gdelt_days,
        "emdat": None,
        "opensky-adsb": hazard,
        "abuse-ch-urlhaus": hazard,
        "abuse-ch-feodo": hazard,
        "polymarket": hazard,
        "uk-police": 30,
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
        deleted_by_source[src] = _prune_source(
            session, source=src, days=settings.retention_news_days, now=now
        )

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


def _database_size_bytes(session: Session) -> int:
    return session.execute(text("SELECT pg_database_size(current_database())")).scalar_one()


def _events_size_bytes(session: Session) -> int:
    return session.execute(text("SELECT pg_total_relation_size('events')")).scalar_one()


def _as_date(value: date | str) -> date:
    # func.date() returns a date on Postgres but an ISO string on SQLite.
    return value if isinstance(value, date) else date.fromisoformat(value)


def enforce_size_cap(
    session: Session,
    *,
    now: datetime | None = None,
    db_size_bytes: int | None = None,
    events_size_bytes: int | None = None,
) -> dict[str, int]:
    """Trim oldest event-days when the database exceeds ``storage_cap_gb``.

    ``pg_database_size`` reports the file high-water mark, which never drops
    after ``DELETE`` — looping "while size > cap: delete" would therefore wipe
    the table down to the floor. Instead the overage is converted to a row
    budget via the events table's average row footprint, and just enough of
    the oldest whole days are deleted in one pass. Keep-forever sources and
    rows newer than ``storage_cap_floor_days`` are never touched.

    ``db_size_bytes`` / ``events_size_bytes`` exist for tests (SQLite has no
    ``pg_database_size``); production leaves them ``None`` to query Postgres.
    """
    started_at = time.monotonic()
    now = now or datetime.now(UTC)
    cap_bytes = settings.storage_cap_gb * 1024**3
    db_size = db_size_bytes if db_size_bytes is not None else _database_size_bytes(session)
    if db_size <= cap_bytes:
        return {"db_size_bytes": db_size, "cap_bytes": cap_bytes, "deleted": 0, "days_trimmed": 0}

    overage = db_size - cap_bytes
    exempt = [src for src, days in retention_days().items() if days is None]
    floor_cutoff = now - timedelta(days=settings.storage_cap_floor_days)

    live_rows = session.execute(select(func.count()).select_from(EventRow)).scalar_one()
    events_size = (
        events_size_bytes if events_size_bytes is not None else _events_size_bytes(session)
    )
    bytes_per_row = (events_size / live_rows) if live_rows else 0.0

    deleted = 0
    days_trimmed = 0
    if bytes_per_row > 0:
        day_col = func.date(EventRow.occurred_at)
        per_day = session.execute(
            select(day_col.label("day"), func.count().label("n"))
            .where(EventRow.occurred_at < floor_cutoff, EventRow.source.notin_(exempt))
            .group_by(day_col)
            .order_by(day_col.asc())
        ).all()
        freed = 0.0
        boundary_day: date | None = None
        for day, n in per_day:
            boundary_day = _as_date(day)
            days_trimmed += 1
            freed += n * bytes_per_row
            if freed >= overage:
                break
        if boundary_day is not None:
            boundary = datetime.combine(boundary_day + timedelta(days=1), dtime.min, tzinfo=UTC)
            boundary = min(boundary, floor_cutoff)
            result = session.execute(
                delete(EventRow).where(
                    EventRow.occurred_at < boundary,
                    EventRow.source.notin_(exempt),
                )
            )
            deleted = result.rowcount or 0

    duration_ms = int((time.monotonic() - started_at) * 1000)
    session.add(
        HousekeepingRunRow(
            job_name="size-cap",
            archived_count=0,
            deleted_count=deleted,
            duration_ms=duration_ms,
            notes=(f"db_size_bytes={db_size}; cap_bytes={cap_bytes}; days_trimmed={days_trimmed}"),
        )
    )
    return {
        "db_size_bytes": db_size,
        "cap_bytes": cap_bytes,
        "deleted": deleted,
        "days_trimmed": days_trimmed,
    }


def prune_brain_narrative(session: Session, *, now: datetime | None = None) -> int:
    """Delete situation narratives older than the news retention window (#409)."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.retention_news_days)
    result = session.execute(delete(BrainNarrativeRow).where(BrainNarrativeRow.created_at < cutoff))
    return result.rowcount or 0


def vacuum_events(bind) -> bool:
    """``VACUUM (ANALYZE) events`` so space freed by the nightly deletes is
    reusable. Must run on an autocommit connection after the deletes commit —
    VACUUM cannot run inside a transaction and skips rows still visible to an
    open one. Postgres-only; returns whether it ran.
    """
    engine = getattr(bind, "engine", bind)
    if engine.dialect.name != "postgresql":
        return False
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        # PARALLEL 0: parallel index vacuum allocates dynamic shared memory
        # beyond the 64 MB /dev/shm Docker default → DiskFull on small boxes.
        conn.execute(text("VACUUM (ANALYZE, PARALLEL 0) events"))
    return True


def run_retention_and_cap(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Nightly housekeeping entry point: retention pass, then size cap.

    A cap failure (e.g. Postgres size functions unavailable) is logged but
    never fails the retention pass whose result is returned.
    """
    now = now or datetime.now(UTC)
    deleted_by_source = prune_events(session, now=now)
    deleted_by_source["brain_narrative"] = prune_brain_narrative(session, now=now)
    try:
        enforce_size_cap(session, now=now)
    except Exception:
        logger.exception("size-cap enforcement failed; retention pass unaffected")
    return deleted_by_source
