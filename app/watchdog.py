"""Ingest watchdog.

Walks ``ingest_health`` once per beat fire and flags sources whose last
successful fetch is older than ``cadence x STALE_MULTIPLIER`` minutes. A
flagged source produces:

1. A row in ``notifications`` (so the frontend ConnectionIndicator can show it)
2. A Pushover message if ``PUSHOVER_TOKEN`` + ``PUSHOVER_USER`` are configured
3. A WARNING log line regardless of Pushover state

Dedup: the ``notifications.dedup_key`` UNIQUE index keeps us from re-paging the
same source more than once per day. Reset happens automatically as a new UTC
day rolls in.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db_models import IngestHealthRow, NotificationRow
from app.settings import settings
from app.sources.rss_registry import feed_cadence_map

logger = logging.getLogger(__name__)


#: Polling cadence in minutes per source. Mirrors the beat schedule in
#: ``app/tasks.py``. Editing one without the other is a bug.
CORE_SOURCE_CADENCE_MIN: dict[str, int] = {
    "yfinance": 5,
    "fred": 1440,  # daily
    "gdelt": 15,
    "acled": 60,
    "emdat": 1440,
    "usgs-quake": 15,
    "gdacs": 15,
    "nasa-firms": 60,
    "eonet": 30,
    "uk-police": 1440,
    "opensky-adsb": 2,
    "abuse-ch-urlhaus": 15,
    "abuse-ch-feodo": 15,
    "polymarket": 30,
}

SOURCE_CADENCE_MIN: dict[str, int] = {
    **CORE_SOURCE_CADENCE_MIN,
    **feed_cadence_map(),
}

#: A source is "stale" once last_success is older than this many cadence
#: windows. With STALE_MULTIPLIER=6, a 15-min fetcher is flagged after 90 min
#: of silence — enough headroom that one missed beat doesn't trip the alarm,
#: tight enough that a real outage pages within an hour.
STALE_MULTIPLIER: int = 6


def _last_success(session: Session, source: str) -> datetime | None:
    """Return the most recent ``last_success`` across the per-day rows for ``source``.

    SQLite drops tzinfo on round-trip, so we re-attach UTC if the driver hands
    back a naive datetime; Postgres returns tz-aware values directly.
    """
    stmt = (
        select(IngestHealthRow.last_success)
        .where(IngestHealthRow.source == source)
        .where(IngestHealthRow.last_success.is_not(None))
        .order_by(IngestHealthRow.day.desc())
        .limit(1)
    )
    row = session.execute(stmt).first()
    if row is None:
        return None
    value = row[0]
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def _pushover_send(message: str) -> None:
    """Best-effort Pushover notification. Silent if credentials missing."""
    if not settings.pushover_token or not settings.pushover_user:
        return
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": settings.pushover_token,
                    "user": settings.pushover_user,
                    "title": "OSINT ingest watchdog",
                    "message": message,
                },
            )
    except httpx.HTTPError as exc:
        logger.warning("watchdog: pushover send failed: %s", exc)


def _persist_notification(session: Session, *, source: str, message: str, today: date) -> bool:
    """Insert a notifications row; return True if a new row was inserted."""
    dedup_key = f"watchdog:stale:{source}:{today.isoformat()}"
    row = {
        "channel": "watchdog",
        "country": None,
        "score_value": None,
        "message": message,
        "dedup_key": dedup_key,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        stmt = (
            pg_insert(NotificationRow)
            .values(row)
            .on_conflict_do_nothing(index_elements=["dedup_key"])
            .returning(NotificationRow.id)
        )
    elif dialect == "sqlite":
        stmt = (
            sqlite_insert(NotificationRow)
            .values(row)
            .on_conflict_do_nothing(index_elements=["dedup_key"])
            .returning(NotificationRow.id)
        )
    else:
        raise NotImplementedError(f"watchdog does not support dialect {dialect!r}")
    result = session.execute(stmt)
    return result.first() is not None


def check_sources(session: Session, *, now: datetime | None = None) -> dict[str, dict[str, object]]:
    """Run one watchdog sweep over every source. Return per-source state."""
    now = now or datetime.now(UTC)
    today = now.date()
    report: dict[str, dict[str, object]] = {}

    for source, cadence_min in SOURCE_CADENCE_MIN.items():
        threshold = timedelta(minutes=cadence_min * STALE_MULTIPLIER)
        last_success = _last_success(session, source)
        is_stale = last_success is None or (now - last_success) > threshold

        report[source] = {
            "last_success": last_success,
            "is_stale": is_stale,
            "alerted": False,
        }

        if not is_stale:
            continue

        if last_success is None:
            message = f"{source}: no successful fetch on record (cadence {cadence_min} min)"
        else:
            age_min = int((now - last_success).total_seconds() / 60)
            message = (
                f"{source}: last_success {age_min} min ago "
                f"(cadence {cadence_min} min x {STALE_MULTIPLIER} = stale)"
            )

        logger.warning("watchdog: %s", message)
        if _persist_notification(session, source=source, message=message, today=today):
            _pushover_send(message)
            report[source]["alerted"] = True

    return report
