"""Tests for `app.housekeeping`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow, HousekeepingRunRow
from app.housekeeping import RETENTION_DAYS, prune_events, retention_days


def _make_event_row(*, source: str, occurred_at: datetime, suffix: str) -> EventRow:
    return EventRow(
        source=source,
        source_event_id=f"{source}:{suffix}",
        occurred_at=occurred_at,
        fetched_at=occurred_at,
        category="hazard",
        severity=0.5,
        confidence=None,
        keywords=[],
        country=None,
        lat=None,
        lon=None,
        payload={"x": 1},
    )


def _seed(session: Session, now: datetime) -> None:
    """Two rows per source: one well inside retention, one well outside."""
    for source, days in RETENTION_DAYS.items():
        if days is None:
            # Keep-forever sources still need fixture data so we can prove no
            # rows are dropped even when the row is ancient.
            ancient = now - timedelta(days=10_000)
            session.add(_make_event_row(source=source, occurred_at=ancient, suffix="ancient"))
            continue
        fresh = now - timedelta(days=max(1, days // 2))
        stale = now - timedelta(days=days + 5)
        session.add(_make_event_row(source=source, occurred_at=fresh, suffix="fresh"))
        session.add(_make_event_row(source=source, occurred_at=stale, suffix="stale"))
    session.commit()


def test_retention_days_reads_settings(monkeypatch):
    monkeypatch.setattr("app.housekeeping.settings.retention_gdelt_days", 1)
    monkeypatch.setattr("app.housekeeping.settings.retention_news_days", 2)
    rd = retention_days()
    assert rd["gdelt"] == 1
    assert rd["rss-bbc-world"] == 2
    assert rd["fred"] is None


def test_prune_drops_stale_keeps_fresh(db_session: Session) -> None:
    now = datetime.now(UTC)
    _seed(db_session, now)

    result = prune_events(db_session, now=now)
    db_session.commit()

    # Each source with a retention window should have dropped exactly 1 row
    # (the stale one). Keep-forever sources should drop 0.
    for source, days in RETENTION_DAYS.items():
        expected = 1 if days is not None else 0
        assert result[source] == expected, f"{source}: expected {expected}, got {result[source]}"

    # Every fresh row must still exist; every stale row gone.
    remaining = db_session.execute(select(EventRow)).scalars().all()
    for row in remaining:
        if RETENTION_DAYS.get(row.source) is None:
            continue  # keep-forever
        assert row.source_event_id.endswith(":fresh") or row.source_event_id.endswith(":ancient")


def test_prune_writes_housekeeping_audit_row(db_session: Session) -> None:
    now = datetime.now(UTC)
    _seed(db_session, now)

    prune_events(db_session, now=now)
    db_session.commit()

    runs = db_session.execute(select(HousekeepingRunRow)).scalars().all()
    assert len(runs) == 1
    run = runs[0]
    assert run.job_name == "events-retention"
    expected_total = sum(1 for d in RETENTION_DAYS.values() if d is not None)
    assert run.deleted_count == expected_total
    assert run.archived_count == 0  # Parquet archival is a follow-up.
    assert run.duration_ms >= 0


def test_prune_is_idempotent_when_no_stale_rows(db_session: Session) -> None:
    now = datetime.now(UTC)
    # Seed only fresh rows.
    for source in RETENTION_DAYS:
        fresh = now - timedelta(hours=1)
        db_session.add(_make_event_row(source=source, occurred_at=fresh, suffix="fresh"))
    db_session.commit()

    result = prune_events(db_session, now=now)
    db_session.commit()

    assert all(n == 0 for n in result.values())
    # Audit row still written so the operator can see the job ran.
    runs = db_session.execute(select(HousekeepingRunRow)).scalars().all()
    assert len(runs) == 1
    assert runs[0].deleted_count == 0
    assert runs[0].notes is None  # No per-source breakdown when nothing pruned.


def test_keep_forever_source_never_drops_rows(db_session: Session) -> None:
    now = datetime.now(UTC)
    # Insert an ancient FRED row well past any plausible retention boundary.
    ancient = now - timedelta(days=20_000)
    db_session.add(_make_event_row(source="fred", occurred_at=ancient, suffix="ancient"))
    db_session.commit()

    result = prune_events(db_session, now=now)
    db_session.commit()

    assert result["fred"] == 0
    remaining = (
        db_session.execute(select(EventRow).where(EventRow.source == "fred")).scalars().all()
    )
    assert len(remaining) == 1
