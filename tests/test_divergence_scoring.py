"""Tests for ``app.divergence.scoring`` core helpers."""

from __future__ import annotations

import math

from app.divergence.scoring import rolling_z


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
