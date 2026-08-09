"""Tests for the retained FRED severity repair."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db_models import EventRow
from app.sources.fred_repair import repair_fred_severity


def _row(day: int, value: float, *, source: str = "fred") -> EventRow:
    occurred_at = datetime(2025, 1, day, tzinfo=UTC)
    return EventRow(
        source=source,
        source_event_id=f"UNRATE:{occurred_at.date().isoformat()}",
        occurred_at=occurred_at,
        fetched_at=occurred_at,
        category="market",
        severity=None,
        confidence=None,
        keywords=["UNRATE", "macro"],
        country="US",
        lat=None,
        lon=None,
        payload={"series_id": "UNRATE", "value": value, "units": "Percent"},
    )


def test_repair_fills_only_scoreable_nulls_and_is_idempotent(db_session: Session) -> None:
    rows = [_row(i + 1, value) for i, value in enumerate([4.0, 4.1, 3.9, 4.0, 4.2, 4.1])]
    db_session.add_all(rows)
    db_session.commit()

    first = repair_fred_severity(db_session)
    db_session.flush()

    assert first.examined == 6
    assert first.repaired == 2
    assert [row.severity for row in rows[:4]] == [None] * 4
    assert all(row.severity is not None for row in rows[4:])

    second = repair_fred_severity(db_session)
    assert second.repaired == 0


def test_repair_ignores_other_sources_and_invalid_payloads(db_session: Session) -> None:
    other = _row(1, 4.0, source="yfinance")
    invalid = _row(2, 4.1)
    invalid.payload = {"series_id": "UNRATE", "value": "not-a-number"}
    db_session.add_all([other, invalid])
    db_session.commit()

    result = repair_fred_severity(db_session)

    assert result.examined == 1
    assert result.repaired == 0
    assert result.skipped_invalid == 1
    assert other.severity is None
