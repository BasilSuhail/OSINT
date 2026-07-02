"""Tests for `app.baselines.metrics` — hand-rolled AUROC / AUPR / Brier."""

from __future__ import annotations

import pytest

from app.baselines.metrics import aupr, auroc, brier


class TestAuroc:
    def test_perfect_ranking(self) -> None:
        assert auroc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0

    def test_reversed_ranking(self) -> None:
        assert auroc([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1]) == 0.0

    def test_all_tied_scores(self) -> None:
        assert auroc([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1]) == 0.5

    def test_partial_hand_computed(self) -> None:
        # pairs: (0.7,1) vs (0.4,0) win; (0.7,1) vs (0.6,0) win;
        #        (0.5,1) vs (0.4,0) win; (0.5,1) vs (0.6,0) loss → 3/4
        assert auroc([0.4, 0.5, 0.6, 0.7], [0, 1, 0, 1]) == 0.75

    def test_degenerate_targets_return_none(self) -> None:
        assert auroc([0.1, 0.9], [1, 1]) is None
        assert auroc([0.1, 0.9], [0, 0]) is None
        assert auroc([], []) is None


class TestAupr:
    def test_perfect_ranking(self) -> None:
        assert aupr([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0

    def test_hand_computed(self) -> None:
        # Descending by score: (0.9,1), (0.8,0), (0.6,1), (0.4,0)
        # AP = mean over positives of precision-at-that-positive:
        #   1st positive at rank 1: precision 1/1
        #   2nd positive at rank 3: precision 2/3
        # AP = (1 + 2/3) / 2 = 5/6
        result = aupr([0.4, 0.6, 0.8, 0.9], [0, 1, 0, 1])
        assert result == pytest.approx(5 / 6)

    def test_degenerate_targets_return_none(self) -> None:
        assert aupr([0.1, 0.9], [0, 0]) is None
        assert aupr([], []) is None


class TestBrier:
    def test_exact(self) -> None:
        # ((0.8-1)^2 + (0.3-0)^2) / 2 = (0.04 + 0.09) / 2
        assert brier([0.8, 0.3], [1, 0]) == pytest.approx(0.065)

    def test_perfect_predictions(self) -> None:
        assert brier([1.0, 0.0], [1, 0]) == 0.0

    def test_empty_returns_none(self) -> None:
        assert brier([], []) is None
