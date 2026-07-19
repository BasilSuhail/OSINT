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


def test_rolling_z_needs_a_full_baseline_before_scoring():
    """Two prior points is not a baseline (#526).

    At index 2 the standard deviation of two values is near zero, so an
    ordinary value read as 3-5 sigma. detect_lead takes the FIRST narrative
    spike, so it locked onto that phantom every time: three unrelated events in
    the gate run produced an identical -58 day lead from exactly this.
    """
    from app.divergence.config import ROLLING_WINDOW_DAYS

    # A step change early in the series must not register while warming up.
    values = [10.0, 10.0, 400.0] + [10.0] * 40
    z = rolling_z(values, window=ROLLING_WINDOW_DAYS)
    assert z[2] == 0.0, "a spike on a two-point baseline is not a measurement"
    assert all(v == 0.0 for v in z[:ROLLING_WINDOW_DAYS])


def test_rolling_z_scores_once_the_baseline_is_complete():
    from app.divergence.config import ROLLING_WINDOW_DAYS

    # A noisy but stable baseline, then a genuine jump. Perfectly flat input
    # would trip the zero-variance guard instead, which is a different path.
    values = [10.0 + (i % 3) for i in range(ROLLING_WINDOW_DAYS)] + [400.0]
    z = rolling_z(values, window=ROLLING_WINDOW_DAYS)
    assert z[ROLLING_WINDOW_DAYS] > 3.0


def test_detect_lead_ignores_the_warmup_phantom():
    """The exact shape that produced -58 in the gate run."""
    from datetime import date, timedelta

    days = [date(2026, 5, 1) + timedelta(days=i) for i in range(61)]
    # Early bump that used to fire at index 2, then a genuine pair later.
    narrative = [100.0, 100.0, 260.0] + [100.0] * 58
    physical = [1.0] * 61
    narrative[50] = 900.0
    physical[46] = 60.0
    series = compute_divergence_series(days, physical, narrative)
    result = detect_lead(series)
    assert result.narrative_spike_day != days[2], "warmup phantom must not be the spike"
    assert result.lead_days is None or result.lead_days > 0
