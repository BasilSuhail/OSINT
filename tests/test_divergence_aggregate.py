"""Tests for ``app.divergence.aggregate.daily_side_counts``."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.db_models import EventRow
from app.divergence.aggregate import daily_side_counts


def _ev(
    session: object,
    *,
    source: str,
    country: str,
    day: date,
    hour: int = 12,
) -> None:
    session.add(
        EventRow(
            source=source,
            source_event_id=f"{source}-{day.isoformat()}-{hour}",
            occurred_at=datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
            fetched_at=datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
            category="hazard",
            keywords=[],
            country=country,
            lat=0.0,
            lon=0.0,
            payload={},
        )
    )


def test_daily_counts_partition_and_fill(db_session) -> None:
    _ev(db_session, source="usgs-quake", country="JP", day=date(2025, 3, 1))
    _ev(db_session, source="usgs-quake", country="JP", day=date(2025, 3, 1), hour=14)
    _ev(db_session, source="gdelt", country="JP", day=date(2025, 3, 3))
    _ev(db_session, source="yfinance", country="JP", day=date(2025, 3, 1))
    db_session.commit()

    days, physical, narrative = daily_side_counts(
        db_session, "JP", date(2025, 3, 1), date(2025, 3, 3)
    )
    assert days == [date(2025, 3, 1), date(2025, 3, 2), date(2025, 3, 3)]
    assert physical == [2.0, 0.0, 0.0]
    assert narrative == [0.0, 0.0, 1.0]


def test_other_country_excluded(db_session) -> None:
    _ev(db_session, source="usgs-quake", country="US", day=date(2025, 3, 1))
    db_session.commit()
    _, physical, _ = daily_side_counts(db_session, "JP", date(2025, 3, 1), date(2025, 3, 1))
    assert physical == [0.0]
