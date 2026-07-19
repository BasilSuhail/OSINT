"""Magnitude-weighted physical series (#528).

The physical side counted rows per country per day, so a M7.3 and a M2.1 each
contributed exactly 1. On the day of a major earthquake the series ticked from
"one quake" to "two quakes" — no spike, and 11 of 16 scored events in the gate
run produced no measurement at all. Magnitude is the entire signal and it was
being discarded.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.db_models import EventRow
from app.divergence.aggregate import daily_physical_intensity


def _quake(session, day: date, magnitude: float, country: str = "JP", eid: str = "") -> None:
    session.add(
        EventRow(
            source="usgs-quake",
            source_event_id=eid or f"{country}-{day}-{magnitude}",
            occurred_at=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
            category="hazard",
            severity=0.4,
            country=country,
            keywords=[],
            payload={"magnitude": magnitude},
        )
    )


def test_a_big_quake_outweighs_several_small_ones(db_session):
    """Counting rows made three tremors look bigger than one disaster."""
    start, end = date(2026, 5, 1), date(2026, 5, 3)
    for i in range(3):
        _quake(db_session, date(2026, 5, 1), 3.0, eid=f"small-{i}")
    _quake(db_session, date(2026, 5, 2), 7.2, eid="big")
    db_session.commit()

    days, values = daily_physical_intensity(db_session, "JP", start, end)
    assert days == [date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3)]
    assert values[1] > values[0], "one M7.2 must outweigh three M3.0"


def test_quiet_days_are_zero(db_session):
    start, end = date(2026, 5, 1), date(2026, 5, 2)
    _quake(db_session, date(2026, 5, 2), 5.0)
    db_session.commit()
    _, values = daily_physical_intensity(db_session, "JP", start, end)
    assert values[0] == 0.0
    assert values[1] > 0.0


def test_uses_the_strongest_event_of_the_day(db_session):
    start = end = date(2026, 5, 1)
    _quake(db_session, start, 4.0, eid="a")
    _quake(db_session, start, 6.6, eid="b")
    db_session.commit()
    _, values = daily_physical_intensity(db_session, "JP", start, end)
    assert values[0] == 6.6


def test_events_without_magnitude_fall_back_to_severity(db_session):
    """GDACS floods and EONET fires carry no magnitude but are still physical."""
    start = end = date(2026, 5, 1)
    db_session.add(
        EventRow(
            source="gdacs",
            source_event_id="flood-1",
            occurred_at=datetime(2026, 5, 1, 12, tzinfo=UTC),
            category="hazard",
            severity=0.8,
            country="JP",
            keywords=[],
            payload={"event_type": "FL"},
        )
    )
    db_session.commit()
    _, values = daily_physical_intensity(db_session, "JP", start, end)
    assert values[0] > 0.0


def test_other_countries_are_excluded(db_session):
    start = end = date(2026, 5, 1)
    _quake(db_session, start, 7.5, country="CL", eid="cl")
    db_session.commit()
    _, values = daily_physical_intensity(db_session, "JP", start, end)
    assert values[0] == 0.0
