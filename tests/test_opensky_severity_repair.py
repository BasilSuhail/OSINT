"""Retained-row repair for OpenSky's legacy constant severity (#865)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db_models import EventRow
from app.sources import opensky_severity_repair


def _add(session, *, source="opensky-adsb", severity=0.0, n=1):
    base = session.query(EventRow).count()
    for i in range(n):
        session.add(
            EventRow(
                source=source,
                source_event_id=f"{source}-{base + i}",
                occurred_at=datetime.now(UTC),
                fetched_at=datetime.now(UTC),
                category="tracking",
                severity=severity,
                country="GB",
                keywords=["adsb"],
                payload={"aircraft_count": i + 1},
            )
        )
    session.commit()


def _severities(session, source="opensky-adsb"):
    return [
        row.severity
        for row in session.query(EventRow).filter(EventRow.source == source).order_by(EventRow.id)
    ]


def _aircraft_counts(session):
    return [
        row.payload["aircraft_count"]
        for row in session.query(EventRow)
        .filter(EventRow.source == "opensky-adsb")
        .order_by(EventRow.id)
    ]


def test_plan_separates_legacy_null_and_unexpected_rows(db_session):
    _add(db_session, severity=0.0, n=3)
    _add(db_session, severity=None, n=2)
    _add(db_session, severity=0.7)

    plan = opensky_severity_repair.plan_repair(db_session)

    assert plan.total_rows == 6
    assert plan.zero_rows == 3
    assert plan.null_rows == 2
    assert plan.unexpected_rows == 1


def test_plan_writes_nothing(db_session):
    _add(db_session, severity=0.0, n=2)

    opensky_severity_repair.plan_repair(db_session)

    assert _severities(db_session) == [0.0, 0.0]


def test_repair_clears_only_known_legacy_zero(db_session):
    _add(db_session, severity=0.0, n=2)
    _add(db_session, severity=None)
    _add(db_session, severity=0.7)

    changed = opensky_severity_repair.apply_repair(db_session)

    assert changed == 2
    assert _severities(db_session) == [None, None, None, 0.7]
    assert _aircraft_counts(db_session) == [1, 2, 1, 1]


def test_other_sources_are_untouched(db_session):
    _add(db_session, source="another-source", severity=0.0)
    _add(db_session, severity=0.0)

    opensky_severity_repair.apply_repair(db_session)

    assert _severities(db_session, source="another-source") == [0.0]


def test_repair_is_idempotent(db_session):
    _add(db_session, severity=0.0, n=4)

    assert opensky_severity_repair.apply_repair(db_session) == 4
    assert opensky_severity_repair.apply_repair(db_session) == 0


def test_batching_covers_every_eligible_row(db_session):
    _add(db_session, severity=0.0, n=7)

    changed = opensky_severity_repair.apply_repair(db_session, batch_size=2)

    assert changed == 7
    assert _severities(db_session) == [None] * 7


def test_rejects_nonpositive_batch_size(db_session):
    with pytest.raises(ValueError, match="batch_size must be positive"):
        opensky_severity_repair.apply_repair(db_session, batch_size=0)
