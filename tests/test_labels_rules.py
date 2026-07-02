"""Tests for `app.labels.rules` — aggregate-adapted P1-P3 label rules.

Boundary cases per the labels-v1.0 spec
(docs/superpowers/specs/2026-07-02-acled-labels-design.md).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.labels.rules import RULES_VERSION, compute_labels


def _row(
    *,
    country: str = "SY",
    week: datetime,
    event_type: str = "Battles",
    events: int = 1,
    fatalities: int = 0,
) -> dict[str, Any]:
    return {
        "country": country,
        "week": week,
        "event_type": event_type,
        "events": events,
        "fatalities": fatalities,
    }


def _codes(labels: list[dict[str, Any]]) -> set[str]:
    return {label["label_code"] for label in labels}


WEEK_JAN = datetime(2024, 1, 6, tzinfo=UTC)
WEEK_JAN_2 = datetime(2024, 1, 13, tzinfo=UTC)
WEEK_FEB = datetime(2024, 2, 3, tzinfo=UTC)


class TestP1BattleFatalities:
    def test_ten_battle_fatalities_in_week_fires(self) -> None:
        labels = compute_labels([_row(week=WEEK_JAN, fatalities=10)])
        assert _codes(labels) == {"P1"}
        (label,) = labels
        assert label["country"] == "SY"
        assert label["bucket_start"] == datetime(2024, 1, 1, tzinfo=UTC)
        assert label["magnitude"] == 10.0

    def test_nine_battle_fatalities_does_not_fire(self) -> None:
        labels = compute_labels([_row(week=WEEK_JAN, fatalities=9)])
        assert _codes(labels) == set()

    def test_fatalities_summed_within_week_across_rows(self) -> None:
        # Regional files split a week across admin1 / sub-event rows.
        rows = [
            _row(week=WEEK_JAN, fatalities=6),
            _row(week=WEEK_JAN, fatalities=4),
        ]
        assert _codes(compute_labels(rows)) == {"P1"}

    def test_fatalities_not_summed_across_weeks(self) -> None:
        rows = [
            _row(week=WEEK_JAN, fatalities=6),
            _row(week=WEEK_JAN_2, fatalities=4),
        ]
        assert _codes(compute_labels(rows)) == set()

    def test_non_battle_fatalities_ignored(self) -> None:
        rows = [_row(week=WEEK_JAN, event_type="Violence against civilians", fatalities=50)]
        assert "P1" not in _codes(compute_labels(rows))

    def test_one_label_per_month_even_with_two_qualifying_weeks(self) -> None:
        rows = [
            _row(week=WEEK_JAN, fatalities=12),
            _row(week=WEEK_JAN_2, fatalities=20),
        ]
        labels = [label for label in compute_labels(rows) if label["label_code"] == "P1"]
        assert len(labels) == 1
        # magnitude = worst qualifying week
        assert labels[0]["magnitude"] == 20.0

    def test_payload_carries_version_and_trigger_weeks(self) -> None:
        (label,) = compute_labels([_row(week=WEEK_JAN, fatalities=10)])
        assert label["payload"]["rules_version"] == RULES_VERSION
        assert "2024-01-06" in label["payload"]["trigger_weeks"]


class TestP2ProtestEscalation:
    def test_five_demo_events_with_one_riot_fires(self) -> None:
        rows = [
            _row(week=WEEK_JAN, event_type="Protests", events=4),
            _row(week=WEEK_JAN, event_type="Riots", events=1),
        ]
        assert "P2" in _codes(compute_labels(rows))

    def test_four_demo_events_does_not_fire(self) -> None:
        rows = [
            _row(week=WEEK_JAN, event_type="Protests", events=3),
            _row(week=WEEK_JAN, event_type="Riots", events=1),
        ]
        assert "P2" not in _codes(compute_labels(rows))

    def test_five_protests_without_riot_does_not_fire(self) -> None:
        rows = [_row(week=WEEK_JAN, event_type="Protests", events=5)]
        assert "P2" not in _codes(compute_labels(rows))

    def test_riot_in_different_week_does_not_fire(self) -> None:
        rows = [
            _row(week=WEEK_JAN, event_type="Protests", events=5),
            _row(week=WEEK_JAN_2, event_type="Riots", events=1),
        ]
        assert "P2" not in _codes(compute_labels(rows))

    def test_magnitude_is_demo_event_count(self) -> None:
        rows = [
            _row(week=WEEK_JAN, event_type="Protests", events=7),
            _row(week=WEEK_JAN, event_type="Riots", events=2),
        ]
        labels = [label for label in compute_labels(rows) if label["label_code"] == "P2"]
        assert labels[0]["magnitude"] == 9.0


class TestP3Intensification:
    def test_doubling_over_floor_fires(self) -> None:
        rows = [
            _row(week=WEEK_JAN, fatalities=20),
            _row(week=WEEK_FEB, fatalities=40),
        ]
        labels = [label for label in compute_labels(rows) if label["label_code"] == "P3"]
        assert len(labels) == 1
        assert labels[0]["bucket_start"] == datetime(2024, 2, 1, tzinfo=UTC)
        assert labels[0]["magnitude"] == 40.0

    def test_below_floor_does_not_fire(self) -> None:
        # 12 → 24 doubles but stays under the 25-fatality floor.
        rows = [
            _row(week=WEEK_JAN, fatalities=12),
            _row(week=WEEK_FEB, fatalities=24),
        ]
        assert "P3" not in _codes(compute_labels(rows))

    def test_less_than_double_does_not_fire(self) -> None:
        rows = [
            _row(week=WEEK_JAN, fatalities=20),
            _row(week=WEEK_FEB, fatalities=39),
        ]
        assert "P3" not in _codes(compute_labels(rows))

    def test_exactly_double_at_floor_fires(self) -> None:
        rows = [
            _row(week=WEEK_JAN, fatalities=13),
            _row(week=WEEK_FEB, fatalities=26),
        ]
        assert "P3" in _codes(compute_labels(rows))

    def test_first_observed_month_never_fires(self) -> None:
        # No prior month to compare against.
        rows = [_row(week=WEEK_JAN, fatalities=100)]
        assert "P3" not in _codes(compute_labels(rows))

    def test_zero_previous_month_counts_as_doubling(self) -> None:
        # Country observed in Jan with zero PV fatalities, spike in Feb.
        rows = [
            _row(week=WEEK_JAN, event_type="Protests", events=1, fatalities=0),
            _row(week=WEEK_FEB, fatalities=30),
        ]
        assert "P3" in _codes(compute_labels(rows))

    def test_gap_month_treated_as_zero(self) -> None:
        # Jan observed, Feb absent (0), Mar spike → doubling from 0.
        rows = [
            _row(week=WEEK_JAN, fatalities=20),
            _row(week=datetime(2024, 3, 2, tzinfo=UTC), fatalities=30),
        ]
        labels = [label for label in compute_labels(rows) if label["label_code"] == "P3"]
        assert [label["bucket_start"] for label in labels] == [datetime(2024, 3, 1, tzinfo=UTC)]

    def test_riots_count_toward_political_violence_fatalities(self) -> None:
        rows = [
            _row(week=WEEK_JAN, event_type="Riots", fatalities=15),
            _row(week=WEEK_FEB, event_type="Riots", fatalities=30),
        ]
        assert "P3" in _codes(compute_labels(rows))

    def test_protest_fatalities_do_not_count(self) -> None:
        # Protests are demonstrations, not political violence, in labels-v1.0.
        rows = [
            _row(week=WEEK_JAN, event_type="Protests", fatalities=20),
            _row(week=WEEK_FEB, event_type="Protests", fatalities=40),
        ]
        assert "P3" not in _codes(compute_labels(rows))


class TestMultiCountry:
    def test_countries_do_not_bleed(self) -> None:
        rows = [
            _row(country="SY", week=WEEK_JAN, fatalities=6),
            _row(country="SD", week=WEEK_JAN, fatalities=6),
        ]
        assert _codes(compute_labels(rows)) == set()

    def test_labels_carry_their_country(self) -> None:
        rows = [
            _row(country="SD", week=WEEK_JAN, fatalities=11),
        ]
        (label,) = compute_labels(rows)
        assert label["country"] == "SD"
