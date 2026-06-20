"""Tests for `app.watchdog`."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import IngestHealthRow, NotificationRow
from app.watchdog import (
    SOURCE_CADENCE_MIN,
    STALE_MULTIPLIER,
    _persist_notification,
    check_sources,
)


def _seed_health(
    session: Session, *, source: str, last_success: datetime | None
) -> None:
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
            _seed_health(
                db_session, source=source, last_success=now - timedelta(minutes=2)
            )
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
            _seed_health(
                db_session, source=source, last_success=now - timedelta(minutes=1)
            )

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
        now = datetime.now(UTC)
        _seed_health(
            db_session, source="gdelt", last_success=now - timedelta(minutes=120)
        )
        # Seed every other source as fresh so only gdelt trips the alarm.
        for source in SOURCE_CADENCE_MIN:
            if source == "gdelt":
                continue
            _seed_health(
                db_session, source=source, last_success=now - timedelta(minutes=1)
            )

        first = check_sources(db_session, now=now)
        db_session.commit()
        second = check_sources(db_session, now=now + timedelta(minutes=5))
        db_session.commit()

        assert first["gdelt"]["alerted"] is True
        assert second["gdelt"]["alerted"] is False  # second sweep blocked by dedup
        rows = db_session.execute(select(NotificationRow)).scalars().all()
        assert len(rows) == 1

    def test_stale_threshold_uses_cadence_times_multiplier(
        self, db_session: Session
    ) -> None:
        now = datetime.now(UTC)
        # yfinance cadence = 5; 5 × 6 = 30 → 25 min ago should be fresh, 35 stale.
        _seed_health(
            db_session, source="yfinance", last_success=now - timedelta(minutes=25)
        )
        report_a = check_sources(db_session, now=now)
        assert report_a["yfinance"]["is_stale"] is False

        # Reset DB, try 35 min.
        db_session.query(NotificationRow).delete()
        db_session.query(IngestHealthRow).delete()
        _seed_health(
            db_session, source="yfinance", last_success=now - timedelta(minutes=35)
        )
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
        _persist_notification(
            db_session, source="gdelt", message="test", today=date(2026, 6, 20)
        )
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


# Placeholder so pytest collects this file even if SQLite RETURNING gets quirky
# on someone's local box; the real assertions above prove the path works.
def test_module_imports() -> None:
    assert callable(check_sources)
    pytest.importorskip("sqlalchemy")
