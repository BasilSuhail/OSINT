"""Tests for ``app.divergence.scoring`` core helpers."""

from __future__ import annotations

import math
from datetime import date, timedelta

from app.divergence.scoring import LeadResult, compute_divergence_series, detect_lead, rolling_z


def test_rolling_z_flat_series_is_zero() -> None:
    assert rolling_z([5.0] * 10, window=5) == [0.0] * 10


def test_rolling_z_spike_is_positive() -> None:
    series = [1.0, 1.0, 1.0, 1.0, 2.0, 10.0]
    z = rolling_z(series, window=5)
    assert z[:5] == [0.0, 0.0, 0.0, 0.0, 0.0]
    assert z[5] > 3.0


def test_rolling_z_warmup_returns_zero_until_two_points() -> None:
    z = rolling_z([3.0, 7.0, 11.0], window=28)
    assert z[0] == 0.0
    assert z[1] == 0.0


def test_rolling_z_no_nan() -> None:
    z = rolling_z([0.0, 0.0, 0.0, 4.0], window=3)
    assert all(not math.isnan(v) for v in z)


def _days(n: int) -> list[date]:
    base = date(2025, 1, 1)
    return [base + timedelta(days=i) for i in range(n)]


def test_physical_leads_narrative_by_three_days() -> None:
    days = _days(40)
    physical = [1.0 + 0.1 * ((i % 3) - 1) for i in range(40)]
    narrative = [1.0] * 40
    physical[30] = 80.0
    narrative[29] = 1.2
    narrative[33] = 200.0
    series = compute_divergence_series(days, physical, narrative)
    result = detect_lead(series)
    assert result == LeadResult(
        physical_spike_day=days[30],
        narrative_spike_day=days[33],
        lead_days=3,
    )


def test_no_narrative_spike_returns_none_lead() -> None:
    days = _days(40)
    series = compute_divergence_series(days, [1.0] * 40, [1.0] * 40)
    result = detect_lead(series)
    assert result.narrative_spike_day is None
    assert result.lead_days is None


def test_divergence_positive_when_physical_moves_first() -> None:
    days = _days(40)
    physical = [1.0 + 0.1 * ((i % 3) - 1) for i in range(40)]
    physical[30] = 80.0
    series = compute_divergence_series(days, physical, [1.0] * 40)
    assert series.divergence[30] > 0
