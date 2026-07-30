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
        assert w.market + w.geopolitical + w.hazard + w.wildfire == pytest.approx(1.0)
        assert w.method_version == DEFAULT_METHOD_VERSION

    def test_custom_weights_renormalised(self) -> None:
        w = WeightingConfig(market=0.5, geopolitical=0.5, hazard=0.0, wildfire=0.0)
        assert w.market + w.geopolitical + w.hazard + w.wildfire == pytest.approx(1.0)

    def test_unnormalised_inputs_renormalised(self) -> None:
        w = WeightingConfig(market=2.0, geopolitical=1.0, hazard=1.0, wildfire=0.0)
        assert w.market + w.geopolitical + w.hazard + w.wildfire == pytest.approx(1.0)
        assert w.market == pytest.approx(0.5)

    def test_all_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            WeightingConfig(market=0.0, geopolitical=0.0, hazard=0.0, wildfire=0.0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            WeightingConfig(market=-0.1, geopolitical=0.5, hazard=0.6)

    def test_as_dict(self) -> None:
        w = WeightingConfig()
        d = w.as_dict()
        assert set(d.keys()) == {"market", "geopolitical", "hazard", "wildfire"}


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

    def test_an_absent_domain_is_excluded_rather_than_imputed(self) -> None:
        # #683. Absent and average are different claims. A domain that produced
        # no signal used to enter the sum as z=0.0 — "exactly average" — which
        # dragged the weighted sum toward 0 and every such score toward
        # sigmoid(0) = 0.5. The countries missing the most data are the quiet
        # ones the index most needs to discriminate.
        signals = {("US", _bucket(2026, 6)): {"market": 6.0}}
        scores = compute_scores(signals)

        # Market is now the whole weight, not a quarter of it.
        assert scores[0].components["z"] == {"market": 6.0}
        assert scores[0].components["weights_used"] == {"market": pytest.approx(1.0)}
        assert scores[0].components["domains_present"] == ["market"]
        assert scores[0].components["weighted_sum"] == pytest.approx(6.0)

    def test_absent_domains_do_not_drag_the_score_toward_one_half(self) -> None:
        # The regression that matters, stated as a comparison: the same single
        # strong signal must not be diluted by three domains that do not exist.
        one_domain = compute_scores({("US", _bucket(2026, 6)): {"market": 6.0}})
        all_four = compute_scores(
            {
                ("US", _bucket(2026, 6)): {
                    "market": 6.0,
                    "geopolitical": 0.0,
                    "hazard": 0.0,
                    "wildfire": 0.0,
                }
            }
        )

        # Four real domains, three of them average: dilution is correct there.
        assert all_four[0].score_value == pytest.approx(_sigmoid(1.5))
        # One real domain: no dilution, because there is nothing to dilute with.
        assert one_domain[0].score_value == pytest.approx(_sigmoid(6.0))
        assert one_domain[0].score_value > all_four[0].score_value

    def test_weights_are_renormalised_over_present_domains_only(self) -> None:
        signals = {("US", _bucket(2026, 6)): {"market": 2.0, "hazard": 2.0}}
        scores = compute_scores(signals)

        used = scores[0].components["weights_used"]
        assert sum(used.values()) == pytest.approx(1.0)
        assert used == {"market": pytest.approx(0.5), "hazard": pytest.approx(0.5)}
        # Equal halves of equal z: the weighted sum is that z, not half of it.
        assert scores[0].components["weighted_sum"] == pytest.approx(2.0)

    def test_a_present_but_zero_domain_still_counts_as_present(self) -> None:
        # An explicit 0.0 is a measurement — "this country was average this
        # month" — and must dilute. Only absence is excluded.
        signals = {("US", _bucket(2026, 6)): {"market": 4.0, "hazard": 0.0}}
        scores = compute_scores(signals)

        assert scores[0].components["domains_present"] == ["hazard", "market"]
        assert scores[0].components["weighted_sum"] == pytest.approx(2.0)

    def test_a_cell_with_no_known_domains_is_not_scored(self) -> None:
        # Nothing to renormalise over. Emitting sigmoid(0) here would be the
        # imputation this issue removes, wearing a different hat.
        signals = {("US", _bucket(2026, 6)): {}}
        assert compute_scores(signals) == []

    def test_unknown_domains_are_ignored_not_scored(self) -> None:
        # A signal the weighting config does not know about must not sneak into
        # the sum with an implied weight.
        signals = {("US", _bucket(2026, 6)): {"market": 2.0, "not_a_domain": 99.0}}
        scores = compute_scores(signals)

        assert scores[0].components["domains_present"] == ["market"]
        assert scores[0].components["weighted_sum"] == pytest.approx(2.0)

    def test_components_breakdown(self) -> None:
        # All four domains present, so the quarter weights apply unchanged. The
        # fixture gained `wildfire` when #683 stopped imputing absent domains —
        # this test is about the components payload, not about absence, and its
        # assertions are unchanged.
        signals = {
            ("US", _bucket(2026, 6)): {
                "market": 3.0,
                "geopolitical": 0.0,
                "hazard": 0.0,
                "wildfire": 0.0,
            }
        }
        scores = compute_scores(signals)
        comp = scores[0].components
        assert comp["z"]["market"] == 3.0
        assert comp["contribution"]["market"] == pytest.approx(0.75)
        assert comp["weighted_sum"] == pytest.approx(0.75)

    def test_method_version_default(self) -> None:
        signals = {("US", _bucket(2026, 6)): {"market": 0.0}}
        scores = compute_scores(signals)
        assert scores[0].method_version == DEFAULT_METHOD_VERSION

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
