"""A near-constant is a constant (#831).

The journal is the only out-of-sample evidence this project has, and 89% of
what is in it is the number 0.5:

```
month     predictions  distinct scores  exactly 0.500
2026-07         1,101              34          91.0%
2026-08           588              27          86.7%
```

The guard meant to prevent this refuses only exact flatness — `min == max`. In
2026-07 the composite took seven distinct values across 519 rows, so one
country differing by a rounding error made 518 identical rows look like a
distribution, and 1,101 forecasts of a constant were recorded as forecasts.

The statistic this needs already exists in the repository. `app/audit/checks.py`
met the identical shape one layer over — a column nominally continuous that is
really a flag — and answered it with the share of rows taking the single most
common value, on the stated grounds that standard deviation alone does not
expose it.
"""

from __future__ import annotations

from app.composite import degeneracy

#: The live shape, reconstructed from the measured monthly counts: 519 rows,
#: seven distinct values, 98.8% of them exactly 0.5.
LIVE_JULY = [0.5] * 513 + [0.49, 0.51, 0.48, 0.52, 0.47, 0.53]

#: A backfill month: every country a different number, sd around 0.10.
HEALTHY_MONTH = [0.30 + (i % 235) * 0.0017 for i in range(235)]


class TestConcentration:
    def test_a_series_that_is_almost_all_one_value_is_refused(self) -> None:
        assert degeneracy.is_degenerate(LIVE_JULY)

    def test_a_backfill_month_is_not(self) -> None:
        """2015-2024 carried a distinct value per country and real spread.
        Refusing those would throw away the only working history there is."""
        assert not degeneracy.is_degenerate(HEALTHY_MONTH)

    def test_the_reason_states_the_concentration(self) -> None:
        reason = degeneracy.describe(LIVE_JULY, label="composite v1")
        assert reason is not None
        assert "98" in reason or "99" in reason
        assert "0.5" in reason

    def test_the_bar_matches_the_one_the_audit_already_uses(self) -> None:
        """Two thresholds for one shape would drift, and then two parts of the
        system would disagree about whether a number carries information."""
        from app.audit.checks import MAX_CONTINUOUS_TOP_SHARE

        assert degeneracy.MAX_TOP_SHARE == MAX_CONTINUOUS_TOP_SHARE

    def test_a_series_just_inside_the_bar_survives(self) -> None:
        """The threshold has to be a line someone can reason about, not a
        gradient. 89 of 100 identical is allowed; 91 is not."""
        assert not degeneracy.is_degenerate([0.5] * 89 + [0.4 + i / 100 for i in range(11)])
        assert degeneracy.is_degenerate([0.5] * 91 + [0.4 + i / 100 for i in range(9)])


class TestWhatMustKeepFailing:
    def test_exact_flatness_is_still_refused(self) -> None:
        assert degeneracy.is_degenerate([0.5] * 500)

    def test_a_single_observation_is_still_not_a_cross_section(self) -> None:
        assert degeneracy.is_degenerate([0.7])
        assert degeneracy.is_degenerate([])

    def test_nulls_do_not_rescue_a_constant(self) -> None:
        assert degeneracy.is_degenerate([0.5, None, 0.5, None, 0.5])


class TestTheJournalStopsWriting:
    def test_the_live_july_shape_would_not_have_been_issued(self) -> None:
        """The whole point: these 519 scores produced 1,101 journal rows, and
        under this rule they produce none."""
        assert degeneracy.describe(LIVE_JULY, label="composite v1.0") is not None

    def test_a_healthy_month_still_issues(self) -> None:
        assert degeneracy.describe(HEALTHY_MONTH, label="composite v1.0") is None
