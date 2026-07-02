"""Tests for `app.coverage.stats` — per-country coverage-bias statistics."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.coverage.stats import compute_coverage, concentration


def _row(country: str, year: int, month: int, *, events: int = 1, fatalities: int = 0) -> dict:
    return {
        "country": country,
        "week": datetime(year, month, 7, tzinfo=UTC),
        "event_type": "Battles",
        "events": events,
        "fatalities": fatalities,
    }


class TestComputeCoverage:
    def test_coverage_vs_observed_months_with_gap(self) -> None:
        rows = [_row("SY", 2020, 1), _row("SY", 2020, 3)]
        (stat,) = compute_coverage(rows)
        assert stat["country"] == "SY"
        assert stat["coverage_months"] == 3
        assert stat["observed_months"] == 2

    def test_volume_arithmetic_two_countries(self) -> None:
        rows = [
            _row("SY", 2020, 1, events=6),
            _row("SY", 2020, 2, events=2),
            _row("US", 2020, 1, events=2),
        ]
        stats = {s["country"]: s for s in compute_coverage(rows)}
        assert stats["SY"]["total_events"] == 8
        assert stats["SY"]["events_per_month"] == 4.0
        assert stats["SY"]["global_share"] == 0.8
        assert stats["US"]["global_share"] == 0.2

    def test_global_share_sums_to_one(self) -> None:
        rows = [_row("SY", 2020, 1, events=3), _row("US", 2020, 1, events=7)]
        assert sum(s["global_share"] for s in compute_coverage(rows)) == pytest.approx(1.0)

    def test_baseline_std(self) -> None:
        # SY monthly volumes: Jan 6, Feb 2 → mean 4 (= events_per_month), pop std 2
        rows = [_row("SY", 2020, 1, events=6), _row("SY", 2020, 2, events=2)]
        (stat,) = compute_coverage(rows)
        assert stat["events_per_month"] == 4.0
        assert stat["baseline_std"] == 2.0

    def test_gap_month_counts_as_zero_in_baseline(self) -> None:
        # Jan 6, Feb missing (0), Mar 6 → mean 4, std sqrt(8)
        rows = [_row("SY", 2020, 1, events=6), _row("SY", 2020, 3, events=6)]
        (stat,) = compute_coverage(rows)
        assert stat["events_per_month"] == 4.0
        assert stat["baseline_std"] == pytest.approx(8**0.5)

    def test_single_month_country_std_zero(self) -> None:
        (stat,) = compute_coverage([_row("US", 2020, 5)])
        assert stat["coverage_months"] == 1
        assert stat["baseline_std"] == 0.0

    def test_fatalities_per_event(self) -> None:
        rows = [_row("SY", 2020, 1, events=4, fatalities=10)]
        (stat,) = compute_coverage(rows)
        assert stat["fatalities_per_event"] == 2.5

    def test_sorted_by_total_events_descending(self) -> None:
        rows = [_row("US", 2020, 1, events=1), _row("SY", 2020, 1, events=9)]
        stats = compute_coverage(rows)
        assert [s["country"] for s in stats] == ["SY", "US"]


class TestConcentration:
    def test_top_n_share_on_skewed_fixture(self) -> None:
        rows = [
            _row("SY", 2020, 1, events=90),
            _row("US", 2020, 1, events=8),
            _row("IS", 2020, 1, events=2),
        ]
        stats = compute_coverage(rows)
        shares = concentration(stats, tops=(1, 2))
        assert shares[1] == 0.9
        assert shares[2] == pytest.approx(0.98)

    def test_top_n_larger_than_country_count(self) -> None:
        stats = compute_coverage([_row("SY", 2020, 1, events=5)])
        assert concentration(stats, tops=(10,))[10] == pytest.approx(1.0)
