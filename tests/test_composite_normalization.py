"""Tests for `app.composite.normalization`."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.composite.normalization import (
    DEFAULT_WINDOW_MONTHS,
    MIN_HISTORY,
    normalize_domain_signals,
    rolling_zscore,
)


def _bucket(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=UTC)


class TestRollingZscore:
    def test_rejects_non_positive_window(self) -> None:
        with pytest.raises(ValueError):
            rolling_zscore([1.0, 2.0], window=0)
        with pytest.raises(ValueError):
            rolling_zscore([1.0, 2.0], window=-3)

    def test_cold_start_returns_zeros(self) -> None:
        values = [0.5, 0.6]
        out = rolling_zscore(values, window=12)
        # Both positions fail MIN_HISTORY (need >=3 prior points).
        assert out == [0.0, 0.0]

    def test_constant_series_zero_after_warmup(self) -> None:
        values = [0.5] * 6
        out = rolling_zscore(values, window=12)
        # Once enough history exists std=0 → emit 0.
        assert all(v == 0.0 for v in out)

    def test_step_change_visible_after_warmup(self) -> None:
        # Vary the history slightly so std > 0; then a 0.9 spike should produce
        # a large positive z.
        values = [0.10, 0.15, 0.10, 0.12, 0.13, 0.9]
        out = rolling_zscore(values, window=12)
        assert out[-1] > 2.0

    def test_window_limits_history(self) -> None:
        # With window=3, the spike's z-score is based on the 3 preceding points
        # only, not the whole history.
        values = [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        out = rolling_zscore(values, window=3)
        # Position 5 sees the previous 3 zeros — std=0 → 0.
        assert out[-1] == 0.0

        # Mix it up so history has non-zero std.
        values = [0.1, 0.2, 0.3, 0.4, 0.5, 5.0]
        out = rolling_zscore(values, window=3)
        # Position 5 history = [0.3, 0.4, 0.5], mean=0.4, std≈0.0816
        # z = (5.0 - 0.4) / 0.0816 ≈ 56.3
        assert out[-1] > 50.0


class TestNormalizeDomainSignals:
    def test_empty_input(self) -> None:
        assert normalize_domain_signals({}) == {}

    def test_cold_start_emits_zero(self) -> None:
        buckets = {
            ("US", _bucket(2026, 6)): {"market": 0.4},
        }
        out = normalize_domain_signals(buckets)
        assert out == {("US", _bucket(2026, 6)): {"market": 0.0}}

    def test_per_country_normalisation(self) -> None:
        # US has 12 noisy quiet months then a spike; GB has 12 truly flat
        # months. The spike should produce a positive US z; GB's z is 0
        # because its history has zero variance.
        us_vals = [0.10, 0.12, 0.09, 0.11, 0.10, 0.13, 0.08, 0.10, 0.11, 0.12, 0.10, 0.11]
        buckets: dict = {}
        for m, v in enumerate(us_vals, start=1):
            buckets[("US", _bucket(2025, m))] = {"market": v}
            buckets[("GB", _bucket(2025, m))] = {"market": 0.1}
        buckets[("US", _bucket(2026, 1))] = {"market": 0.9}
        buckets[("GB", _bucket(2026, 1))] = {"market": 0.1}

        out = normalize_domain_signals(buckets)
        us_jan = out[("US", _bucket(2026, 1))]["market"]
        gb_jan = out[("GB", _bucket(2026, 1))]["market"]
        assert us_jan > 5.0  # spike vs 12 noisy-but-quiet months
        assert gb_jan == 0.0  # std=0 history → 0

    def test_independent_per_domain(self) -> None:
        # market deviations should not influence geopolitical z-scores.
        us_vals = [0.10, 0.12, 0.09, 0.11, 0.10, 0.13, 0.08, 0.10, 0.11, 0.12, 0.10, 0.11]
        buckets: dict = {}
        for m, v in enumerate(us_vals, start=1):
            buckets[("US", _bucket(2025, m))] = {"market": v, "geopolitical": 0.5}
        buckets[("US", _bucket(2026, 1))] = {"market": 0.9, "geopolitical": 0.5}

        out = normalize_domain_signals(buckets)
        jan = out[("US", _bucket(2026, 1))]
        assert jan["market"] > 5.0
        assert jan["geopolitical"] == 0.0  # geo history is constant → std=0 → 0

    def test_default_window_matches_module_constant(self) -> None:
        assert DEFAULT_WINDOW_MONTHS == 12
        assert MIN_HISTORY == 3
