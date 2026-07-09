"""Tests for `app.housekeeping`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow, HousekeepingRunRow
from app.housekeeping import (
    enforce_size_cap,
    prune_events,
    retention_days,
    run_retention_and_cap,
    vacuum_events,
)


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
    for source, days in retention_days().items():
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
    for source, days in retention_days().items():
        expected = 1 if days is not None else 0
        assert result[source] == expected, f"{source}: expected {expected}, got {result[source]}"

    # Every fresh row must still exist; every stale row gone.
    remaining = db_session.execute(select(EventRow)).scalars().all()
    for row in remaining:
        if retention_days().get(row.source) is None:
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
    expected_total = sum(1 for d in retention_days().values() if d is not None)
    assert run.deleted_count == expected_total
    assert run.archived_count == 0  # Parquet archival is a follow-up.
    assert run.duration_ms >= 0


def test_prune_is_idempotent_when_no_stale_rows(db_session: Session) -> None:
    now = datetime.now(UTC)
    # Seed only fresh rows.
    for source in retention_days():
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


GIB = 1024**3


def _event_count(session: Session) -> int:
    return len(session.execute(select(EventRow)).scalars().all())


def test_size_cap_noop_under_cap(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.housekeeping.settings.storage_cap_gb", 1)
    now = datetime.now(UTC)
    db_session.add(
        _make_event_row(source="opensky-adsb", occurred_at=now - timedelta(days=20), suffix="old")
    )
    db_session.commit()

    result = enforce_size_cap(db_session, now=now, db_size_bytes=GIB // 2, events_size_bytes=1_000)
    db_session.commit()

    assert result["deleted"] == 0
    assert _event_count(db_session) == 1
    # No-op under cap → no audit row.
    assert db_session.execute(select(HousekeepingRunRow)).scalars().all() == []


def test_size_cap_trims_oldest_days_to_cover_overage(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.housekeeping.settings.storage_cap_gb", 1)
    monkeypatch.setattr("app.housekeeping.settings.storage_cap_floor_days", 7)
    now = datetime.now(UTC)
    for days_ago, suffix in [(40, "d40"), (39, "d39"), (20, "d20"), (3, "d3")]:
        db_session.add(
            _make_event_row(
                source="opensky-adsb", occurred_at=now - timedelta(days=days_ago), suffix=suffix
            )
        )
    db_session.commit()

    # 4 rows, 4000 bytes of events table → 1000 bytes/row. Overage of 1500
    # bytes needs 2 rows freed → the two oldest days go, day 20 and day 3 stay.
    result = enforce_size_cap(
        db_session, now=now, db_size_bytes=GIB + 1_500, events_size_bytes=4_000
    )
    db_session.commit()

    assert result["deleted"] == 2
    assert result["days_trimmed"] == 2
    remaining = {
        row.source_event_id for row in db_session.execute(select(EventRow)).scalars().all()
    }
    assert remaining == {"opensky-adsb:d20", "opensky-adsb:d3"}
    runs = db_session.execute(select(HousekeepingRunRow)).scalars().all()
    assert len(runs) == 1
    assert runs[0].job_name == "size-cap"
    assert runs[0].deleted_count == 2


def test_size_cap_never_deletes_inside_floor(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.housekeeping.settings.storage_cap_gb", 1)
    monkeypatch.setattr("app.housekeeping.settings.storage_cap_floor_days", 7)
    now = datetime.now(UTC)
    for days_ago, suffix in [(2, "d2"), (3, "d3"), (5, "d5")]:
        db_session.add(
            _make_event_row(
                source="opensky-adsb", occurred_at=now - timedelta(days=days_ago), suffix=suffix
            )
        )
    db_session.commit()

    # Massively over cap, but every row is newer than the floor → nothing
    # deleted; audit row still written so the operator sees the breach.
    result = enforce_size_cap(db_session, now=now, db_size_bytes=11 * GIB, events_size_bytes=3_000)
    db_session.commit()

    assert result["deleted"] == 0
    assert _event_count(db_session) == 3
    runs = db_session.execute(select(HousekeepingRunRow)).scalars().all()
    assert len(runs) == 1
    assert runs[0].job_name == "size-cap"
    assert runs[0].deleted_count == 0


def test_size_cap_exempts_keep_forever_sources(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.housekeeping.settings.storage_cap_gb", 1)
    now = datetime.now(UTC)
    old = now - timedelta(days=100)
    for source in ["fred", "emdat", "opensky-adsb"]:
        db_session.add(_make_event_row(source=source, occurred_at=old, suffix="ancient"))
    db_session.commit()

    result = enforce_size_cap(db_session, now=now, db_size_bytes=11 * GIB, events_size_bytes=3_000)
    db_session.commit()

    assert result["deleted"] == 1
    remaining = {row.source for row in db_session.execute(select(EventRow)).scalars().all()}
    assert remaining == {"fred", "emdat"}


def test_cap_failure_does_not_break_retention(db_session: Session, monkeypatch) -> None:
    now = datetime.now(UTC)
    stale = now - timedelta(days=500)
    db_session.add(_make_event_row(source="opensky-adsb", occurred_at=stale, suffix="stale"))
    db_session.commit()

    def boom(*args, **kwargs):
        raise RuntimeError("pg_database_size unavailable")

    monkeypatch.setattr("app.housekeeping.enforce_size_cap", boom)

    result = run_retention_and_cap(db_session, now=now)
    db_session.commit()

    # Retention still ran and its result is returned despite the cap blowing up.
    assert result["opensky-adsb"] == 1
    assert _event_count(db_session) == 0


def test_vacuum_events_is_noop_off_postgres(db_session: Session) -> None:
    # VACUUM is Postgres-only; on SQLite (tests) it must skip, not raise.
    assert vacuum_events(db_session.get_bind()) is False


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
