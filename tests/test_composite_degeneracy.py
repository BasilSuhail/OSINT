"""Refusing to predict from a score with no variance (#589).

Pure logic — every case runs against plain values, no database.
"""

from __future__ import annotations

from app.composite import degeneracy


class TestSpread:
    def test_a_varying_score_is_not_degenerate(self):
        assert degeneracy.is_degenerate([0.1, 0.4, 0.9]) is False

    def test_one_value_repeated_is_degenerate(self):
        """The live composite's shape: 0.5 for every country (#586)."""
        assert degeneracy.is_degenerate([0.5] * 184) is True

    def test_a_single_observation_is_degenerate(self):
        """One country is not a cross-section — nothing to rank against."""
        assert degeneracy.is_degenerate([0.5]) is True

    def test_no_observations_is_degenerate(self):
        assert degeneracy.is_degenerate([]) is True

    def test_a_tiny_but_real_spread_is_not_degenerate(self):
        """Only exact flatness is refused. Judging 'enough' variance is a
        modelling decision, not this guard's business."""
        assert degeneracy.is_degenerate([0.5, 0.5, 0.500001]) is False

    def test_nulls_are_ignored_rather_than_counted_as_a_value(self):
        assert degeneracy.is_degenerate([0.5, None, 0.5]) is True
        assert degeneracy.is_degenerate([0.1, None, 0.9]) is False


class TestReport:
    def test_describes_what_it_refused_and_why(self):
        report = degeneracy.describe([0.5] * 184, label="composite v2.0")

        assert report is not None
        assert "composite v2.0" in report
        assert "184" in report
        assert "0.5" in report

    def test_returns_none_when_there_is_nothing_to_object_to(self):
        assert degeneracy.describe([0.1, 0.4, 0.9], label="composite v2.0") is None
