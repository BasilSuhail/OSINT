"""Tests for `scripts.backfill_gdacs_onset`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow
from scripts.backfill_gdacs_onset import parse_onset, run

FETCHED = datetime(2026, 8, 24, 10, 49, tzinfo=UTC)
ONSET = datetime(2026, 8, 20, 10, 8, tzinfo=UTC)


def _row(
    *,
    suffix: str,
    occurred_at: datetime,
    from_date: str | None = "2026-08-20T10:08:00",
    source: str = "gdacs",
) -> EventRow:
    payload: dict[str, object] = {}
    if from_date is not None:
        payload["from_date"] = from_date
    return EventRow(
        source=source,
        source_event_id=f"EQ:{suffix}",
        occurred_at=occurred_at,
        fetched_at=FETCHED,
        category="hazard",
        keywords=[],
        payload=payload,
    )


def test_a_fetch_stamped_quake_gets_its_own_moment_back(db_session: Session) -> None:
    db_session.add(_row(suffix="1560644", occurred_at=FETCHED))
    db_session.commit()

    counts = run(db_session, batch_size=100, dry_run=False)

    assert counts["repaired"] == 1
    stored = db_session.execute(select(EventRow)).scalars().one().occurred_at
    assert (stored if stored.tzinfo else stored.replace(tzinfo=UTC)) == ONSET


def test_a_row_that_was_never_wrong_is_left_untouched(db_session: Session) -> None:
    #: Rewriting a correct row to the same value still moves `updated_at`, and
    #: the map polls that column to pull revised rows to open consoles — so a
    #: no-op repair would send every hazard row to every viewer.
    db_session.add(_row(suffix="correct", occurred_at=ONSET))
    db_session.commit()

    counts = run(db_session, batch_size=100, dry_run=False)

    assert counts["repaired"] == 0
    assert counts["already_correct"] == 1


def test_a_row_with_no_usable_onset_is_left_alone(db_session: Session) -> None:
    db_session.add(_row(suffix="none", occurred_at=FETCHED, from_date=None))
    db_session.add(_row(suffix="junk", occurred_at=FETCHED, from_date="not a date"))
    db_session.commit()

    counts = run(db_session, batch_size=100, dry_run=False)

    assert counts["no_onset"] == 2
    assert counts["repaired"] == 0
    for row in db_session.execute(select(EventRow)).scalars().all():
        stored = row.occurred_at
        assert (stored if stored.tzinfo else stored.replace(tzinfo=UTC)) == FETCHED


def test_other_sources_are_not_touched(db_session: Session) -> None:
    db_session.add(_row(suffix="eonet", occurred_at=FETCHED, source="eonet"))
    db_session.commit()

    counts = run(db_session, batch_size=100, dry_run=False)

    assert counts["scanned"] == 0


def test_dry_run_counts_without_writing(db_session: Session) -> None:
    db_session.add(_row(suffix="1560644", occurred_at=FETCHED))
    db_session.commit()

    counts = run(db_session, batch_size=100, dry_run=True)

    assert counts["repaired"] == 1
    stored = db_session.execute(select(EventRow)).scalars().one().occurred_at
    assert (stored if stored.tzinfo else stored.replace(tzinfo=UTC)) == FETCHED


def test_every_row_is_seen_across_batches(db_session: Session) -> None:
    for n in range(7):
        db_session.add(_row(suffix=str(n), occurred_at=FETCHED + timedelta(minutes=n)))
    db_session.commit()

    counts = run(db_session, batch_size=2, dry_run=False)

    assert counts["scanned"] == 7
    assert counts["repaired"] == 7


def test_parse_onset_handles_the_shapes_the_payload_carries() -> None:
    assert parse_onset("2026-08-20T10:08:00") == ONSET
    assert parse_onset("2026-08-20T10:08:00+00:00") == ONSET
    assert parse_onset(None) is None
    assert parse_onset("") is None
    assert parse_onset("not a date") is None
    assert parse_onset(12345) is None
