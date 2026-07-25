"""Re-deriving stored FIRMS severity from FRP (#579).

Replaces tests/test_firms_backfill.py. That sweep recovered severity from
`payload.confidence_raw` — the right value of the wrong quantity, and on the
stored rows the two run non-monotonic, so it spread an inversion rather than
fixing a gap.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.db_models import EventRow
from app.sources import firms_frp_resweep
from app.sources.nasa_firms_fetcher import frp_to_severity


def _add(session, *, source="nasa-firms", severity=None, confidence_raw="n", frp="10.0", n=1):
    """Insert n FIRMS-shaped rows."""
    base = session.query(EventRow).count()
    for i in range(n):
        payload = {"brightness": 300.0}
        if confidence_raw is not None:
            payload["confidence_raw"] = confidence_raw
        if frp is not None:
            payload["frp"] = frp
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
            )
        )
    session.commit()


def _severities(session, source="nasa-firms"):
    return [row.severity for row in session.query(EventRow).filter(EventRow.source == source).all()]


def test_plan_counts_rows_that_would_change(db_session):
    _add(db_session, frp="10.0", severity=None, n=3)
    _add(db_session, frp="500.0", severity=0.9, n=2)

    plan = firms_frp_resweep.plan_resweep(db_session)

    assert plan.total_rows == 5
    assert plan.rewritable_rows == 5
    assert plan.unreadable_rows == 0
    assert plan.unchanged_rows == 0


def test_plan_writes_nothing(db_session):
    _add(db_session, frp="10.0", severity=None, n=3)
    firms_frp_resweep.plan_resweep(db_session)
    assert _severities(db_session) == [None, None, None]


def test_rows_swept_by_the_old_confidence_backfill_are_corrected(db_session):
    # #577 set these from confidence. They are exactly the rows that must move.
    _add(db_session, confidence_raw="h", frp="2.0", severity=0.9)

    firms_frp_resweep.apply_resweep(db_session)

    expected = frp_to_severity("2.0", confidence_raw="h")
    assert _severities(db_session) == [expected]
    assert expected is not None and expected < 0.9


def test_the_confidence_inversion_is_gone_after_a_resweep(db_session):
    # The measured non-monotonicity: a low-confidence 500 MW fire ranked below
    # a high-confidence 2 MW one under the old mapping.
    _add(db_session, confidence_raw="l", frp="500.0", severity=0.2)
    _add(db_session, confidence_raw="h", frp="2.0", severity=0.9)

    firms_frp_resweep.apply_resweep(db_session)

    big, small = _severities(db_session)
    assert big > small


def test_unreadable_frp_clears_a_stale_severity(db_session):
    # A value from a superseded method is worse than an absent one: the
    # composite skips NULL but would happily score the stale number.
    _add(db_session, frp=None, confidence_raw="h", severity=0.9)

    firms_frp_resweep.apply_resweep(db_session)

    assert _severities(db_session) == [None]


def test_unreadable_confidence_is_reported_not_silently_skipped(db_session):
    _add(db_session, frp="10.0", confidence_raw="bananas", severity=None)

    plan = firms_frp_resweep.plan_resweep(db_session)

    assert plan.unreadable_rows == 1
    assert plan.rewritable_rows == 0


def test_other_sources_are_untouched(db_session):
    _add(db_session, source="usgs", severity=0.75, frp=None, confidence_raw=None)
    _add(db_session, frp="10.0", severity=None)

    firms_frp_resweep.apply_resweep(db_session)

    assert _severities(db_session, source="usgs") == [0.75]


def test_is_idempotent(db_session):
    _add(db_session, frp="10.0", severity=None, n=4)

    first = firms_frp_resweep.apply_resweep(db_session)
    second = firms_frp_resweep.apply_resweep(db_session)

    assert first == 4
    assert second == 0


def test_a_second_plan_reports_everything_as_unchanged(db_session):
    _add(db_session, frp="10.0", severity=None, n=4)
    firms_frp_resweep.apply_resweep(db_session)

    plan = firms_frp_resweep.plan_resweep(db_session)

    assert plan.unchanged_rows == 4
    assert plan.rewritable_rows == 0


def test_batching_covers_every_row(db_session):
    _add(db_session, frp="10.0", severity=None, n=7)

    changed = firms_frp_resweep.apply_resweep(db_session, batch_size=2)

    assert changed == 7
    assert all(s is not None for s in _severities(db_session))


def test_distinct_frp_values_get_distinct_severities(db_session):
    # The whole point: severity is continuous in FRP now, not three values.
    for frp in ("1.0", "20.0", "300.0"):
        _add(db_session, frp=frp, severity=None)

    firms_frp_resweep.apply_resweep(db_session)

    assert len(set(_severities(db_session))) == 3


def test_rejects_a_nonsense_batch_size(db_session):
    try:
        firms_frp_resweep.apply_resweep(db_session, batch_size=0)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
