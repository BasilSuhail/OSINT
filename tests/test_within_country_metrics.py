"""Within-country concordance and per-country AUROC (#582).

Protocol: docs/within-country-eval.md, frozen before the evaluation was run.
"""

from __future__ import annotations

import pytest

from app.within import metrics


def _rows(*triples):
    """(country, score, target) -> the record shape the metrics consume."""
    return [{"country": c, "score": s, "target": t} for c, s, t in triples]


class TestPooledConcordance:
    def test_perfect_ranking_within_the_only_country(self):
        rows = _rows(("US", 0.9, 1), ("US", 0.1, 0))

        assert metrics.within_country_concordance(rows) == 1.0

    def test_inverted_ranking_scores_zero(self):
        rows = _rows(("US", 0.1, 1), ("US", 0.9, 0))

        assert metrics.within_country_concordance(rows) == 0.0

    def test_ties_count_a_half(self):
        rows = _rows(("US", 0.5, 1), ("US", 0.5, 0))

        assert metrics.within_country_concordance(rows) == 0.5

    def test_pairs_never_cross_country_boundaries(self):
        """The whole point: a country's positives compare only to its own negatives.

        Pooled, this looks perfectly separable — every US score beats every GB
        score and the US month is the positive. Within country, neither country
        ranks its own positive above its own negative.
        """
        rows = _rows(
            ("US", 0.9, 1),
            ("US", 0.8, 0),
            ("GB", 0.2, 0),
            ("GB", 0.3, 1),
        )

        # US: 0.9 > 0.8 -> 1.0. GB: 0.3 > 0.2 -> 1.0. One pair each.
        assert metrics.within_country_concordance(rows) == 1.0

    def test_a_country_that_is_pooled_separable_but_within_country_blind(self):
        """A constant-per-country score: pooled it separates, within country it cannot."""
        rows = _rows(
            ("US", 0.9, 1),
            ("US", 0.9, 0),
            ("GB", 0.1, 1),
            ("GB", 0.1, 0),
        )

        assert metrics.within_country_concordance(rows) == 0.5

    def test_countries_weight_by_their_pair_count(self):
        """US contributes 2 pairs (both right), GB contributes 1 (wrong): 2/3."""
        rows = _rows(
            ("US", 0.9, 1),
            ("US", 0.1, 0),
            ("US", 0.2, 0),
            ("GB", 0.1, 1),
            ("GB", 0.9, 0),
        )

        assert metrics.within_country_concordance(rows) == pytest.approx(2 / 3)

    def test_a_country_with_no_negatives_contributes_nothing(self):
        rows = _rows(("US", 0.9, 1), ("US", 0.8, 1), ("GB", 0.9, 1), ("GB", 0.1, 0))

        assert metrics.within_country_concordance(rows) == 1.0

    def test_no_usable_pairs_anywhere_returns_none(self):
        """Degenerate input returns None so callers print n/a, never a fake number."""
        rows = _rows(("US", 0.9, 1), ("GB", 0.8, 1))

        assert metrics.within_country_concordance(rows) is None

    def test_empty_input_returns_none(self):
        assert metrics.within_country_concordance([]) is None


class TestMeanPerCountryAuroc:
    def test_averages_unweighted_across_qualifying_countries(self):
        """US ranks perfectly, GB inverted; equal weight gives 0.5."""
        rows = _rows(
            *[("US", 0.9 + i / 100, 1) for i in range(3)],
            *[("US", 0.1 + i / 100, 0) for i in range(3)],
            *[("GB", 0.1 + i / 100, 1) for i in range(3)],
            *[("GB", 0.9 + i / 100, 0) for i in range(3)],
        )

        assert metrics.mean_per_country_auroc(rows, min_per_class=3) == pytest.approx(0.5)

    def test_countries_below_the_minimum_are_excluded(self):
        """GB has 1 of each and is dropped, so the mean is US alone."""
        rows = _rows(
            *[("US", 0.9 + i / 100, 1) for i in range(3)],
            *[("US", 0.1 + i / 100, 0) for i in range(3)],
            ("GB", 0.1, 1),
            ("GB", 0.9, 0),
        )

        assert metrics.mean_per_country_auroc(rows, min_per_class=3) == 1.0

    def test_returns_none_when_no_country_qualifies(self):
        rows = _rows(("US", 0.9, 1), ("US", 0.1, 0))

        assert metrics.mean_per_country_auroc(rows, min_per_class=3) is None

    def test_reports_how_many_countries_qualified(self):
        rows = _rows(
            *[("US", 0.9 + i / 100, 1) for i in range(3)],
            *[("US", 0.1 + i / 100, 0) for i in range(3)],
            ("GB", 0.1, 1),
            ("GB", 0.9, 0),
        )

        assert metrics.qualifying_countries(rows, min_per_class=3) == 1


class TestBootstrap:
    def test_resamples_countries_not_rows(self):
        """A perfectly-ranking panel bootstraps to an interval containing 1.0."""
        rows = _rows(
            *[(f"C{c}", 0.9, 1) for c in range(10)],
            *[(f"C{c}", 0.1, 0) for c in range(10)],
        )

        low, high = metrics.bootstrap_ci(
            rows, metrics.within_country_concordance, resamples=200, seed=20260703
        )

        assert low == 1.0 and high == 1.0

    def test_a_coin_flip_panel_has_an_interval_spanning_a_half(self):
        rows = _rows(
            *[(f"C{c}", 0.9 if c % 2 else 0.1, 1) for c in range(20)],
            *[(f"C{c}", 0.1 if c % 2 else 0.9, 0) for c in range(20)],
        )

        low, high = metrics.bootstrap_ci(
            rows, metrics.within_country_concordance, resamples=200, seed=20260703
        )

        assert low <= 0.5 <= high

    def test_is_deterministic_for_a_given_seed(self):
        rows = _rows(
            *[(f"C{c}", c / 10, 1) for c in range(10)],
            *[(f"C{c}", 0.05, 0) for c in range(10)],
        )
        kwargs = {"resamples": 100, "seed": 20260703}

        first = metrics.bootstrap_ci(rows, metrics.within_country_concordance, **kwargs)
        second = metrics.bootstrap_ci(rows, metrics.within_country_concordance, **kwargs)

        assert first == second

    def test_returns_none_when_the_statistic_is_undefined(self):
        rows = _rows(("US", 0.9, 1), ("GB", 0.8, 1))

        assert metrics.bootstrap_ci(
            rows, metrics.within_country_concordance, resamples=50, seed=1
        ) == (None, None)
