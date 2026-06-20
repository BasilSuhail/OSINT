"""Tests for `app.composite.config` and `app.composite.scoring`."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.composite.config import DEFAULT_METHOD_VERSION, WeightingConfig
from app.composite.scoring import (
    MONTH_BUCKET,
    _sigmoid,
    compute_scores,
)


def _bucket(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=UTC)


class TestWeightingConfig:
    def test_defaults_sum_to_one(self) -> None:
        w = WeightingConfig()
        assert w.market + w.geopolitical + w.hazard == pytest.approx(1.0)
        assert w.method_version == DEFAULT_METHOD_VERSION

    def test_custom_weights_renormalised(self) -> None:
        w = WeightingConfig(market=0.5, geopolitical=0.5, hazard=0.0)
        assert w.market + w.geopolitical + w.hazard == pytest.approx(1.0)

    def test_unnormalised_inputs_renormalised(self) -> None:
        w = WeightingConfig(market=2.0, geopolitical=1.0, hazard=1.0)
        assert w.market + w.geopolitical + w.hazard == pytest.approx(1.0)
        assert w.market == pytest.approx(0.5)

    def test_all_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            WeightingConfig(market=0.0, geopolitical=0.0, hazard=0.0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            WeightingConfig(market=-0.1, geopolitical=0.5, hazard=0.6)

    def test_as_dict(self) -> None:
        w = WeightingConfig()
        d = w.as_dict()
        assert set(d.keys()) == {"market", "geopolitical", "hazard"}


class TestSigmoid:
    def test_zero_to_half(self) -> None:
        assert _sigmoid(0.0) == pytest.approx(0.5)

    def test_large_positive(self) -> None:
        assert _sigmoid(20.0) > 0.99

    def test_large_negative(self) -> None:
        assert _sigmoid(-20.0) < 0.01

    def test_monotonic(self) -> None:
        assert _sigmoid(-1.0) < _sigmoid(0.0) < _sigmoid(1.0)


class TestComputeScores:
    def test_empty_input(self) -> None:
        assert compute_scores({}) == []

    def test_zero_z_yields_half(self) -> None:
        signals = {("US", _bucket(2026, 6)): {"market": 0.0, "geopolitical": 0.0, "hazard": 0.0}}
        scores = compute_scores(signals)
        assert len(scores) == 1
        assert scores[0].score_value == pytest.approx(0.5)

    def test_positive_z_pushes_above_half(self) -> None:
        signals = {("US", _bucket(2026, 6)): {"market": 3.0, "geopolitical": 2.0, "hazard": 1.0}}
        scores = compute_scores(signals)
        assert scores[0].score_value > 0.8

    def test_missing_domain_treated_as_zero(self) -> None:
        signals = {("US", _bucket(2026, 6)): {"market": 6.0}}
        scores = compute_scores(signals)
        # weight 1/3 * 6 = 2 → sigmoid(2) ≈ 0.88
        assert scores[0].score_value > 0.85
        assert scores[0].components["z"]["geopolitical"] == 0.0
        assert scores[0].components["z"]["hazard"] == 0.0

    def test_components_breakdown(self) -> None:
        signals = {("US", _bucket(2026, 6)): {"market": 3.0, "geopolitical": 0.0, "hazard": 0.0}}
        scores = compute_scores(signals)
        comp = scores[0].components
        assert comp["z"]["market"] == 3.0
        assert comp["contribution"]["market"] == pytest.approx(1.0)
        assert comp["weighted_sum"] == pytest.approx(1.0)

    def test_method_version_default(self) -> None:
        signals = {("US", _bucket(2026, 6)): {"market": 0.0}}
        scores = compute_scores(signals)
        assert scores[0].method_version == "v1.0"

    def test_method_version_override(self) -> None:
        signals = {("US", _bucket(2026, 6)): {"market": 0.0}}
        scores = compute_scores(signals, method_version="v1.1")
        assert scores[0].method_version == "v1.1"

    def test_bucket_length_is_month(self) -> None:
        signals = {("US", _bucket(2026, 6)): {"market": 0.0}}
        scores = compute_scores(signals)
        assert scores[0].bucket_length == MONTH_BUCKET

    def test_score_name_default_composite(self) -> None:
        signals = {("US", _bucket(2026, 6)): {"market": 0.0}}
        scores = compute_scores(signals)
        assert scores[0].score_name == "composite"

    def test_score_value_always_in_unit_interval(self) -> None:
        for z in (-100.0, -1.0, 0.0, 1.0, 100.0):
            signals = {("US", _bucket(2026, 6)): {"market": z}}
            scores = compute_scores(signals)
            assert 0.0 <= scores[0].score_value <= 1.0
