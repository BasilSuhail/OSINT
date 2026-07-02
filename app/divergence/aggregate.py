"""I/O layer: read events from the store into per-day side counts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow
from app.divergence.config import classify_side


def daily_side_counts(
    session: Session, country: str, start: date, end: date
) -> tuple[list[date], list[float], list[float]]:
    """Return contiguous daily physical and narrative counts for one country."""
    iso = country.upper()
    window_start = datetime(start.year, start.month, start.day, tzinfo=UTC)
    window_end = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
    stmt = (
        select(EventRow)
        .where(EventRow.country == iso)
        .where(EventRow.occurred_at >= window_start)
        .where(EventRow.occurred_at < window_end)
    )

    physical: dict[date, int] = {}
    narrative: dict[date, int] = {}
    for ev in session.execute(stmt).scalars():
        side = classify_side(ev.source)
        if side is None:
            continue
        day = ev.occurred_at.astimezone(UTC).date()
        bucket = physical if side == "physical" else narrative
        bucket[day] = bucket.get(day, 0) + 1

    days: list[date] = []
    physical_series: list[float] = []
    narrative_series: list[float] = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        physical_series.append(float(physical.get(cursor, 0)))
        narrative_series.append(float(narrative.get(cursor, 0)))
        cursor += timedelta(days=1)
    return days, physical_series, narrative_series
