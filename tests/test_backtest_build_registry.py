"""Anchor selection for the gate's event registry (#518)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.backtest.build_registry import select_anchors


def _feature(place: str, day: date, mag: float = 6.5) -> dict:
    return {
        "properties": {
            "place": place,
            "mag": mag,
            "time": int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000),
            "url": "https://example.test/quake",
        }
    }


def test_drops_quakes_with_no_country():
    """A quake at sea has no national news volume to compare against."""
    features = [
        _feature("south of the Kermadec Islands", date(2026, 5, 1)),
        _feature("2 km WSW of Sicaya, Peru", date(2026, 5, 1)),
    ]
    anchors = select_anchors(features)
    assert [a["country"] for a in anchors] == ["PE"]


def test_enforces_separation_within_a_country():
    """Two shocks a week apart share a 60-day window, so the second is not an
    independent test of the same claim."""
    features = [
        _feature("Sicaya, Peru", date(2026, 5, 1)),
        _feature("Lima, Peru", date(2026, 5, 8)),
        _feature("Cusco, Peru", date(2026, 7, 1)),
    ]
    anchors = select_anchors(features)
    assert [a["date"] for a in anchors] == [date(2026, 5, 1), date(2026, 7, 1)]


def test_separate_countries_are_independent():
    features = [
        _feature("Sicaya, Peru", date(2026, 5, 1)),
        _feature("Honshu, Japan", date(2026, 5, 2)),
    ]
    assert len(select_anchors(features)) == 2


def test_ids_are_stable_and_descriptive():
    anchors = select_anchors([_feature("Sicaya, Peru", date(2026, 5, 1), mag=6.4)])
    assert anchors[0]["id"] == "pe-20260501-m6.4"
    assert "Sicaya" in anchors[0]["notes"]
