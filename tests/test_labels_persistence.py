"""Tests for `app.labels.persistence` — idempotent upsert into the labels table."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import LabelRow
from app.labels.persistence import purge_label_source, upsert_labels


def _label(
    *,
    country: str = "SY",
    bucket_start: datetime | None = None,
    label_code: str = "P1",
    magnitude: float = 12.0,
) -> dict[str, Any]:
    return {
        "country": country,
        "bucket_start": bucket_start or datetime(2024, 1, 1, tzinfo=UTC),
        "label_code": label_code,
        "magnitude": magnitude,
        "payload": {"rules_version": "labels-v1.0", "trigger_weeks": ["2024-01-06"]},
    }


def test_insert_returns_count(db_session: Session) -> None:
    assert upsert_labels([_label(), _label(label_code="P2")], db_session) == 2


def test_rerun_is_idempotent(db_session: Session) -> None:
    upsert_labels([_label()], db_session)
    upsert_labels([_label()], db_session)
    rows = db_session.execute(select(LabelRow)).scalars().all()
    assert len(rows) == 1


def test_rerun_refreshes_magnitude_and_payload(db_session: Session) -> None:
    upsert_labels([_label(magnitude=12.0)], db_session)
    updated = _label(magnitude=15.0)
    updated["payload"]["trigger_weeks"] = ["2024-01-06", "2024-01-13"]
    upsert_labels([updated], db_session)
    (row,) = db_session.execute(select(LabelRow)).scalars().all()
    assert row.magnitude == 15.0
    assert row.payload["trigger_weeks"] == ["2024-01-06", "2024-01-13"]


def test_row_fields_stamped(db_session: Session) -> None:
    upsert_labels([_label()], db_session)
    (row,) = db_session.execute(select(LabelRow)).scalars().all()
    assert row.label_source == "acled-aggregates"
    assert row.bucket_length.days >= 28
    assert row.locked_at is not None


def test_duplicate_within_batch_collapsed(db_session: Session) -> None:
    assert upsert_labels([_label(magnitude=10.0), _label(magnitude=20.0)], db_session) == 1
    (row,) = db_session.execute(select(LabelRow)).scalars().all()
    assert row.magnitude == 20.0


def test_empty_input_is_noop(db_session: Session) -> None:
    assert upsert_labels([], db_session) == 0


def test_purge_removes_only_this_labelers_rows(db_session: Session) -> None:
    upsert_labels([_label(), _label(label_code="P2")], db_session)
    other = LabelRow(
        country="US",
        bucket_start=datetime(2024, 1, 1, tzinfo=UTC),
        bucket_length=timedelta(days=31),
        label_code="P4",
        label_source="market-crisis",
        payload={},
    )
    db_session.add(other)
    db_session.commit()
    assert purge_label_source(db_session) == 2
    rows = db_session.execute(select(LabelRow)).scalars().all()
    assert [row.label_source for row in rows] == ["market-crisis"]


def test_batching_splits_large_inputs(db_session: Session) -> None:
    labels = [_label(label_code=f"P{i}") for i in range(1, 6)]
    assert upsert_labels(labels, db_session, batch_size=2) == 5
    assert len(db_session.execute(select(LabelRow)).scalars().all()) == 5
