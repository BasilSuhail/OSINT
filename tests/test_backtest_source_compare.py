"""Comparing two narrative sources on the window where both exist (#557)."""

from datetime import date, timedelta

import pytest

from app.backtest import source_compare
from app.divergence.config import ROLLING_WINDOW_DAYS


def _days(n: int, start=date(2026, 4, 20)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


class TestSpearman:
    def test_identical_series_correlate_perfectly(self):
        assert source_compare.spearman([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0]) == pytest.approx(
            1.0
        )

    def test_reversed_series_anticorrelate_perfectly(self):
        assert source_compare.spearman([1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]) == pytest.approx(
            -1.0
        )

    def test_monotone_rescaling_does_not_change_the_answer(self):
        # The whole point of a rank correlation here: the archive counts
        # mentions in the thousands, the DOC API counts articles in the tens.
        # Only the ordering is comparable.
        a = [1.0, 5.0, 2.0, 9.0]
        assert source_compare.spearman(a, [v * 1000 for v in a]) == pytest.approx(1.0)

    def test_ties_share_an_average_rank(self):
        # Quiet days tie at zero constantly; without midranks the coefficient
        # drifts with how many of them there are.
        assert source_compare.spearman([1.0, 1.0, 2.0], [1.0, 1.0, 2.0]) == pytest.approx(1.0)

    def test_a_flat_series_has_no_correlation_to_report(self):
        assert source_compare.spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None

    def test_mismatched_lengths_are_refused(self):
        with pytest.raises(ValueError):
            source_compare.spearman([1.0, 2.0], [1.0])


def _noisy_baseline(n: int) -> list[float]:
    """A baseline with variance in it.

    `rolling_z` returns 0.0 for a zero-variance prior window, so a perfectly
    flat series can never spike however large the jump after it. Real narrative
    volume is never flat; test fixtures have to not be either.
    """
    return [10.0 + (i % 3) for i in range(n)]


class TestFirstSpikeDay:
    def test_finds_the_day_the_gate_would_call_the_narrative_spike(self):
        days = _days(ROLLING_WINDOW_DAYS + 3)
        values = [*_noisy_baseline(len(days) - 1), 900.0]
        assert source_compare.first_spike_day(days, values) == days[-1]

    def test_returns_none_when_nothing_crosses_the_threshold(self):
        days = _days(ROLLING_WINDOW_DAYS + 3)
        assert source_compare.first_spike_day(days, _noisy_baseline(len(days))) is None

    def test_a_perfectly_flat_series_never_spikes(self):
        # Not a quirk to work around — it is why the fixtures above carry
        # jitter, and why a comparison run over a dead country reports nothing
        # rather than agreement.
        days = _days(ROLLING_WINDOW_DAYS + 3)
        values = [*([10.0] * (len(days) - 1)), 99999.0]
        assert source_compare.first_spike_day(days, values) is None

    def test_reports_the_first_spike_not_the_largest(self):
        days = _days(ROLLING_WINDOW_DAYS + 4)
        values = [*_noisy_baseline(ROLLING_WINDOW_DAYS + 1), 600.0, 10.0, 5000.0]
        assert source_compare.first_spike_day(days, values) == days[ROLLING_WINDOW_DAYS + 1]

    def test_a_lower_threshold_never_finds_a_spike_later(self):
        # Lowering tau can only pull the first crossing earlier — at 0.5 the
        # baseline's own jitter is enough to cross, which is exactly why the
        # gate's tau is not set there.
        days = _days(ROLLING_WINDOW_DAYS + 3)
        values = [*_noisy_baseline(len(days) - 1), 900.0]
        assert source_compare.first_spike_day(days, values, tau=99.0) is None
        strict = source_compare.first_spike_day(days, values, tau=1.5)
        loose = source_compare.first_spike_day(days, values, tau=0.5)
        assert strict == days[-1]
        assert loose is not None and loose <= strict


class TestCompare:
    def _baseline_then_spike(self, spike_index: int, n: int) -> list[float]:
        values = _noisy_baseline(n)
        values[spike_index] = 900.0
        return values

    def test_agreeing_sources_report_a_zero_day_gap(self):
        n = ROLLING_WINDOW_DAYS + 5
        days = _days(n)
        doc = self._baseline_then_spike(n - 1, n)
        archive = self._baseline_then_spike(n - 1, n)
        result = source_compare.compare(days, doc, archive)
        assert result.doc_spike_day == result.archive_spike_day
        assert result.spike_gap_days == 0

    def test_a_source_that_spikes_a_day_late_is_reported_as_such(self):
        # This is the number that matters. The gate consumes spike timing, so
        # two series can correlate beautifully and still disagree about the
        # only thing it reads.
        n = ROLLING_WINDOW_DAYS + 6
        days = _days(n)
        doc = self._baseline_then_spike(n - 2, n)
        archive = self._baseline_then_spike(n - 1, n)
        result = source_compare.compare(days, doc, archive)
        assert result.spike_gap_days == 1

    def test_gap_is_none_when_only_one_source_spikes(self):
        n = ROLLING_WINDOW_DAYS + 5
        days = _days(n)
        result = source_compare.compare(
            days, self._baseline_then_spike(n - 1, n), _noisy_baseline(n)
        )
        assert result.doc_spike_day is not None
        assert result.archive_spike_day is None
        assert result.spike_gap_days is None

    def test_carries_the_day_count_it_was_measured_over(self):
        n = ROLLING_WINDOW_DAYS + 5
        days = _days(n)
        result = source_compare.compare(days, _noisy_baseline(n), _noisy_baseline(n))
        assert result.days == n

    def test_refuses_a_window_too_short_to_establish_a_baseline(self):
        # rolling_z returns 0.0 until a full baseline exists, so a short window
        # cannot spike at all. Comparing spike days over one would report
        # perfect agreement on two series that were never measured.
        n = ROLLING_WINDOW_DAYS - 1
        with pytest.raises(ValueError):
            source_compare.compare(_days(n), [10.0] * n, [10.0] * n)

    def test_refuses_series_that_do_not_line_up_with_the_days(self):
        with pytest.raises(ValueError):
            source_compare.compare(_days(ROLLING_WINDOW_DAYS + 5), [10.0], [10.0])
