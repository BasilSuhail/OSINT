"""I/O layer: read events from the store into per-day side series.

`daily_side_counts` lived here until #497. It counted rows per side, which the
physical side stopped using at #528, and it had no production callers left —
only tests, which kept a dead shape alive and implied a live path that did not
exist.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow
from app.divergence.config import classify_side

#: Physical events carrying no magnitude — floods, wildfires, volcanic alerts —
#: are placed on the magnitude scale through their severity so a severe flood
#: is not silently worth less than a trivial tremor.
_SEVERITY_TO_MAGNITUDE = 10.0


def daily_physical_intensity(
    session: Session, country: str, start: date, end: date
) -> tuple[list[date], list[float]]:
    """Daily physical intensity for one country: the strongest event each day.

    Counting rows threw away the only thing that mattered (#528). A M7.3 and a
    M2.1 each contributed exactly 1, so on the day of a major earthquake the
    series ticked from "one quake" to "two quakes" — no spike worth detecting,
    and 11 of 16 scored events in the lead-time gate produced no measurement.

    Intensity is the day's strongest event rather than a sum: an earthquake is
    one physical fact, and adding its aftershocks together would let a swarm of
    tremors outrank a disaster. Days with nothing are a real zero.
    """
    iso = country.upper()
    window_start = datetime(start.year, start.month, start.day, tzinfo=UTC)
    window_end = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
    stmt = (
        select(EventRow)
        .where(EventRow.country == iso)
        .where(EventRow.occurred_at >= window_start)
        .where(EventRow.occurred_at < window_end)
    )

    strongest: dict[date, float] = {}
    for ev in session.execute(stmt).scalars():
        if classify_side(ev.source) != "physical":
            continue
        payload = ev.payload if isinstance(ev.payload, dict) else {}
        magnitude = payload.get("magnitude")
        if magnitude is None:
            value = float(ev.severity or 0.0) * _SEVERITY_TO_MAGNITUDE
        else:
            try:
                value = float(magnitude)
            except (TypeError, ValueError):
                continue
        day = ev.occurred_at.astimezone(UTC).date()
        if value > strongest.get(day, 0.0):
            strongest[day] = value

    days: list[date] = []
    values: list[float] = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        values.append(strongest.get(cursor, 0.0))
        cursor += timedelta(days=1)
    return days, values
