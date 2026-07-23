"""Tests for `app.watchdog`."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import tasks
from app.db_models import EventRow, IngestHealthRow, NotificationRow
from app.watchdog import (
    SOURCE_CADENCE_MIN,
    STALE_MULTIPLIER,
    _persist_notification,
    check_footprint_coverage,
    check_sources,
)


def _seed_health(session: Session, *, source: str, last_success: datetime | None) -> None:
    today = last_success.date() if last_success else date.today()
    session.add(
        IngestHealthRow(
            source=source,
            day=today,
            success_n=1 if last_success else 0,
            failure_n=0,
            last_success=last_success,
            last_failure=None,
        )
    )
    session.commit()


class TestCheckSources:
    def test_fresh_source_not_flagged(self, db_session: Session) -> None:
        now = datetime.now(UTC)
        for source in SOURCE_CADENCE_MIN:
            _seed_health(db_session, source=source, last_success=now - timedelta(minutes=2))
        report = check_sources(db_session, now=now)
        for source in SOURCE_CADENCE_MIN:
            assert report[source]["is_stale"] is False, source
            assert report[source]["alerted"] is False, source

    def test_silent_source_with_no_health_row_is_stale(self, db_session: Session) -> None:
        now = datetime.now(UTC)
        report = check_sources(db_session, now=now)
        for source in SOURCE_CADENCE_MIN:
            assert report[source]["is_stale"] is True
            assert report[source]["alerted"] is True

    def test_stale_source_writes_notification(self, db_session: Session) -> None:
        now = datetime.now(UTC)
        # GDELT cadence = 15 min; STALE_MULTIPLIER = 6 → 90 min threshold.
        _seed_health(
            db_session,
            source="gdelt",
            last_success=now - timedelta(minutes=120),
        )
        # Seed every other source as fresh so they don't trip the alarm too.
        for source in SOURCE_CADENCE_MIN:
            if source == "gdelt":
                continue
            _seed_health(db_session, source=source, last_success=now - timedelta(minutes=1))

        report = check_sources(db_session, now=now)
        db_session.commit()

        assert report["gdelt"]["is_stale"] is True
        assert report["gdelt"]["alerted"] is True

        rows = db_session.execute(select(NotificationRow)).scalars().all()
        assert len(rows) == 1
        assert rows[0].channel == "watchdog"
        assert "gdelt" in rows[0].message
        assert rows[0].dedup_key.endswith(":gdelt:" + now.date().isoformat())

    def test_dedup_blocks_second_alert_same_day(self, db_session: Session) -> None:
        # Pin to midday UTC: the dedup is keyed by calendar day, and the second
        # sweep is now + 5 min — using the live clock made this flake whenever the
        # suite ran in the last 5 minutes before UTC midnight (the two sweeps
        # straddled two days, so the dedup never engaged).
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        _seed_health(db_session, source="gdelt", last_success=now - timedelta(minutes=120))
        # Seed every other source as fresh so only gdelt trips the alarm.
        for source in SOURCE_CADENCE_MIN:
            if source == "gdelt":
                continue
            _seed_health(db_session, source=source, last_success=now - timedelta(minutes=1))

        first = check_sources(db_session, now=now)
        db_session.commit()
        second = check_sources(db_session, now=now + timedelta(minutes=5))
        db_session.commit()

        assert first["gdelt"]["alerted"] is True
        assert second["gdelt"]["alerted"] is False  # second sweep blocked by dedup
        rows = db_session.execute(select(NotificationRow)).scalars().all()
        assert len(rows) == 1

    def test_stale_threshold_uses_cadence_times_multiplier(self, db_session: Session) -> None:
        now = datetime.now(UTC)
        # yfinance cadence = 5; 5 x 6 = 30 → 25 min ago should be fresh, 35 stale.
        _seed_health(db_session, source="yfinance", last_success=now - timedelta(minutes=25))
        report_a = check_sources(db_session, now=now)
        assert report_a["yfinance"]["is_stale"] is False

        # Reset DB, try 35 min.
        db_session.query(NotificationRow).delete()
        db_session.query(IngestHealthRow).delete()
        _seed_health(db_session, source="yfinance", last_success=now - timedelta(minutes=35))
        report_b = check_sources(db_session, now=now + timedelta(days=1))
        assert report_b["yfinance"]["is_stale"] is True


class TestPersistNotification:
    def test_first_insert_returns_true(self, db_session: Session) -> None:
        ok = _persist_notification(
            db_session, source="gdelt", message="test", today=date(2026, 6, 20)
        )
        db_session.commit()
        assert ok is True

    def test_duplicate_insert_returns_false(self, db_session: Session) -> None:
        _persist_notification(db_session, source="gdelt", message="test", today=date(2026, 6, 20))
        db_session.commit()
        ok = _persist_notification(
            db_session, source="gdelt", message="test", today=date(2026, 6, 20)
        )
        db_session.commit()
        assert ok is False


def test_cadence_and_multiplier_sane() -> None:
    # Catch accidental edits that would break the alert math.
    assert STALE_MULTIPLIER == 6
    assert SOURCE_CADENCE_MIN["yfinance"] == 5
    assert SOURCE_CADENCE_MIN["nasa-firms"] == 60
    assert SOURCE_CADENCE_MIN["fred"] == 1440


def test_watchdog_covers_every_scheduled_fetcher() -> None:
    schedule = tasks.app.conf.beat_schedule
    scheduled = {
        entry["args"][0] for entry in schedule.values() if entry["task"] == "app.tasks.run_fetcher"
    }
    assert scheduled.issubset(SOURCE_CADENCE_MIN)


# Placeholder so pytest collects this file even if SQLite RETURNING gets quirky
# on someone's local box; the real assertions above prove the path works.
def test_module_imports() -> None:
    assert callable(check_sources)
    pytest.importorskip("sqlalchemy")


def _hazard(session: Session, *, minutes_old: int, payload: dict) -> None:
    now = datetime.now(UTC)
    session.add(
        EventRow(
            source="gdacs",
            source_event_id=f"EQ:{payload.get('n', len(payload))}-{minutes_old}-{id(payload)}",
            occurred_at=now - timedelta(minutes=minutes_old),
            fetched_at=now - timedelta(minutes=minutes_old),
            category="hazard",
            severity=0.6,
            keywords=[],
            payload=payload,
        )
    )


class TestFootprintCoverage:
    """#604 hid for weeks because nothing watched enrichment OUTPUT — ingest
    health only knows GDACS answered, which it did the whole time."""

    def test_healthy_coverage_is_not_flagged(self, db_session: Session) -> None:
        for i in range(30):
            _hazard(db_session, minutes_old=180, payload={"n": i, "footprint_geojson": {"f": 1}})
        db_session.commit()

        report = check_footprint_coverage(db_session)

        assert report["coverage"] == 1.0
        assert report["alerted"] is False

    def test_collapsed_coverage_pages_once(self, db_session: Session) -> None:
        for i in range(30):
            _hazard(db_session, minutes_old=180, payload={"n": i})
        db_session.commit()

        first = check_footprint_coverage(db_session)
        second = check_footprint_coverage(db_session)

        assert first["coverage"] == 0.0
        assert first["alerted"] is True
        assert second["alerted"] is False, "paged twice for the same day"
        notes = db_session.execute(select(NotificationRow)).scalars().all()
        assert len(notes) == 1
        assert "footprint" in notes[0].message

    def test_rows_with_no_upstream_geometry_do_not_drag_coverage_down(
        self, db_session: Session
    ) -> None:
        # A quake with no ShakeMap is stamped, not broken — it must leave the
        # denominator or the alarm would ring forever.
        stamped = "2026-01-01T00:00:00+00:00"
        for i in range(30):
            _hazard(db_session, minutes_old=180, payload={"n": i, "footprint_checked_at": stamped})
        for i in range(30, 40):
            _hazard(db_session, minutes_old=180, payload={"n": i, "footprint_geojson": {"f": 1}})
        db_session.commit()

        report = check_footprint_coverage(db_session)

        assert report["eligible"] == 10
        assert report["coverage"] == 1.0
        assert report["alerted"] is False

    def test_freshly_ingested_rows_are_given_time_to_enrich(self, db_session: Session) -> None:
        for i in range(30):
            _hazard(db_session, minutes_old=2, payload={"n": i})
        db_session.commit()

        report = check_footprint_coverage(db_session)

        assert report["eligible"] == 0
        assert report["alerted"] is False

    def test_a_thin_sample_never_pages(self, db_session: Session) -> None:
        # Right after a database wipe there is nothing to conclude from.
        _hazard(db_session, minutes_old=180, payload={"n": 1})
        db_session.commit()

        report = check_footprint_coverage(db_session)

        assert report["alerted"] is False
