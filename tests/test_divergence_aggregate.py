"""Tests for ``app.divergence.aggregate`` — the physical side's daily intensity."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.db_models import EventRow
from app.divergence.aggregate import daily_physical_intensity
from app.divergence.config import INTENSITY_BLIND_SOURCES, classify_side


def _ev(
    session: object,
    *,
    source: str,
    country: str,
    day: date,
    hour: int = 12,
    severity: float | None = None,
    payload: dict | None = None,
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
            severity=severity,
            payload=payload or {},
        )
    )


def test_intensity_is_the_days_strongest_event(db_session) -> None:
    _ev(
        db_session,
        source="usgs-quake",
        country="JP",
        day=date(2025, 3, 1),
        payload={"magnitude": 4.1},
    )
    _ev(
        db_session,
        source="usgs-quake",
        country="JP",
        day=date(2025, 3, 1),
        hour=14,
        payload={"magnitude": 7.3},
    )
    db_session.commit()
    days, values = daily_physical_intensity(db_session, "JP", date(2025, 3, 1), date(2025, 3, 1))
    assert days == [date(2025, 3, 1)]
    assert values == [7.3]


def test_days_with_nothing_are_a_real_zero(db_session) -> None:
    _ev(
        db_session,
        source="usgs-quake",
        country="JP",
        day=date(2025, 3, 1),
        payload={"magnitude": 5.0},
    )
    db_session.commit()
    _, values = daily_physical_intensity(db_session, "JP", date(2025, 3, 1), date(2025, 3, 3))
    assert values == [5.0, 0.0, 0.0]


def test_other_country_excluded(db_session) -> None:
    _ev(
        db_session,
        source="usgs-quake",
        country="US",
        day=date(2025, 3, 1),
        payload={"magnitude": 6},
    )
    db_session.commit()
    _, values = daily_physical_intensity(db_session, "JP", date(2025, 3, 1), date(2025, 3, 1))
    assert values == [0.0]


def test_narrative_sources_never_reach_the_physical_side(db_session) -> None:
    _ev(db_session, source="gdelt", country="JP", day=date(2025, 3, 1), severity=1.0)
    db_session.commit()
    _, values = daily_physical_intensity(db_session, "JP", date(2025, 3, 1), date(2025, 3, 1))
    assert values == [0.0]


class TestIntensityBlindSources:
    """A source that cannot express intensity must not sit on the physical side.

    nasa-firms carries no severity and no magnitude; opensky-adsb hard-codes
    severity 0.0. Both were classified physical, and both scored
    `float(severity or 0.0) * 10 == 0.0`, which never beats the 0.0 default —
    so 594,323 of 595,353 physical rows silently read as "nothing happened"
    rather than "cannot measure" (#497).
    """

    def test_the_blind_sources_are_excluded_from_divergence_entirely(self) -> None:
        for source in INTENSITY_BLIND_SOURCES:
            assert classify_side(source) is None, f"{source} still claims a divergence side"

    def test_a_blind_source_is_not_quietly_reclassified_as_narrative(self) -> None:
        # Excluding must mean excluded. Half a million fire pixels arriving on
        # the narrative side would be far worse than contributing nothing.
        assert classify_side("nasa-firms") != "narrative"
        assert classify_side("opensky-adsb") != "narrative"

    def test_a_blind_source_cannot_mask_a_real_event(self, db_session) -> None:
        _ev(db_session, source="nasa-firms", country="JP", day=date(2025, 3, 1))
        _ev(db_session, source="opensky-adsb", country="JP", day=date(2025, 3, 1), severity=0.0)
        _ev(
            db_session,
            source="usgs-quake",
            country="JP",
            day=date(2025, 3, 1),
            hour=15,
            payload={"magnitude": 6.2},
        )
        db_session.commit()
        _, values = daily_physical_intensity(db_session, "JP", date(2025, 3, 1), date(2025, 3, 1))
        assert values == [6.2]

    def test_sources_that_can_express_intensity_stay_physical(self) -> None:
        for source in ("usgs-quake", "gdacs", "eonet"):
            assert classify_side(source) == "physical"
