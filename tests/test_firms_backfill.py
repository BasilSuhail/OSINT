"""Sweeping stored FIRMS rows that #574 left with no severity (#577).

#574 taught the fetcher to parse VIIRS `l`/`n`/`h`, but only for rows fetched
afterwards. 462,643 rows were already stored with severity NULL and their
confidence still sitting in `payload.confidence_raw`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.db_models import EventRow
from app.sources import firms_backfill


def _add(session, *, source="nasa-firms", severity=None, confidence_raw="n", n=1, **extra):
    """Insert n FIRMS-shaped rows, returning the payload key under test."""
    base = session.query(EventRow).count()
    for i in range(n):
        payload = {"brightness": 300.0, "frp": 1.0}
        if confidence_raw is not None:
            payload["confidence_raw"] = confidence_raw
        payload.update(extra.pop("payload", {}))
        session.add(
            EventRow(
                source=source,
                source_event_id=f"{source}-{base + i}",
                occurred_at=datetime.now(UTC),
                fetched_at=datetime.now(UTC),
                category="hazard",
                severity=severity,
                keywords=["fire"],
                payload=payload,
                **extra,
            )
        )
    session.commit()


def test_reports_rows_whose_confidence_is_recoverable(db_session):
    _add(db_session, confidence_raw="n", n=3)
    _add(db_session, confidence_raw="h", n=2)

    plan = firms_backfill.plan_backfill(db_session)

    assert plan.total_rows == 5
    assert {(g.confidence_raw, g.severity, g.rows) for g in plan.groups} == {
        ("n", 0.5, 3),
        ("h", 0.9, 2),
    }


def test_reporting_writes_nothing(db_session):
    _add(db_session, confidence_raw="n", n=3)

    firms_backfill.plan_backfill(db_session)

    assert db_session.query(EventRow).filter(EventRow.severity.isnot(None)).count() == 0


def test_apply_sets_severity_from_the_stored_confidence(db_session):
    _add(db_session, confidence_raw="l", n=2)
    _add(db_session, confidence_raw="h", n=1)

    plan = firms_backfill.plan_backfill(db_session)
    updated = firms_backfill.apply_backfill(db_session, plan)

    assert updated == 3
    severities = sorted(r.severity for r in db_session.query(EventRow).all())
    assert severities == [0.2, 0.2, 0.9]


def test_leaves_rows_that_already_have_a_severity(db_session):
    _add(db_session, confidence_raw="h", severity=0.42, n=1)

    plan = firms_backfill.plan_backfill(db_session)

    assert plan.total_rows == 0
    assert firms_backfill.apply_backfill(db_session, plan) == 0
    assert db_session.query(EventRow).one().severity == 0.42


def test_ignores_other_sources(db_session):
    _add(db_session, source="gdacs", confidence_raw="h", n=2)

    plan = firms_backfill.plan_backfill(db_session)

    assert plan.total_rows == 0


def test_counts_rows_whose_confidence_cannot_be_recovered_separately(db_session):
    """A row with no usable confidence is reported, never silently written."""
    _add(db_session, confidence_raw=None, n=2)
    _add(db_session, confidence_raw="", n=1)
    _add(db_session, confidence_raw="garbage", n=1)
    _add(db_session, confidence_raw="n", n=5)

    plan = firms_backfill.plan_backfill(db_session)

    assert plan.total_rows == 5
    assert plan.unrecoverable_rows == 4
    assert firms_backfill.apply_backfill(db_session, plan) == 5
    assert db_session.query(EventRow).filter(EventRow.severity.is_(None)).count() == 4


def test_numeric_modis_confidence_survives_the_same_path(db_session):
    _add(db_session, confidence_raw="80", n=1)

    plan = firms_backfill.plan_backfill(db_session)
    firms_backfill.apply_backfill(db_session, plan)

    assert db_session.query(EventRow).one().severity == 0.8


def test_apply_is_idempotent(db_session):
    _add(db_session, confidence_raw="n", n=4)

    first = firms_backfill.apply_backfill(db_session, firms_backfill.plan_backfill(db_session))
    second = firms_backfill.apply_backfill(db_session, firms_backfill.plan_backfill(db_session))

    assert (first, second) == (4, 0)
