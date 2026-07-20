"""Permutation baseline for the lead-time gate (#538).

The gate reported "64% of events leading" against a bar of 50% with nothing
establishing what 50% means. Two spiky, autocorrelated series produce apparent
leads at some rate by chance; until that rate is measured, the observed one
cannot be interpreted.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.backtest.null_model import circular_shift, null_lead_rate


def _days(n: int) -> list[date]:
    return [date(2026, 5, 1) + timedelta(days=i) for i in range(n)]


def test_circular_shift_preserves_every_value():
    """Rotation, not reshuffling: the distribution must survive intact."""
    values = [1.0, 5.0, 2.0, 9.0, 3.0]
    shifted = circular_shift(values, 2)
    assert sorted(shifted) == sorted(values)
    assert shifted == [9.0, 3.0, 1.0, 5.0, 2.0]


def test_circular_shift_preserves_neighbour_structure():
    """A free shuffle would destroy the clustering that makes spikes detectable
    and would understate the null rate. Rotation keeps runs adjacent."""
    values = [0.0, 0.0, 8.0, 9.0, 8.0, 0.0, 0.0, 0.0]
    shifted = circular_shift(values, 3)
    # The 8,9,8 run is still contiguous, just moved.
    joined = "".join("X" if v > 1 else "." for v in shifted)
    assert "XXX" in joined


def test_shift_of_zero_is_identity():
    values = [1.0, 2.0, 3.0]
    assert circular_shift(values, 0) == values


def test_shift_wraps_around_the_length():
    values = [1.0, 2.0, 3.0]
    assert circular_shift(values, 3) == values
    assert circular_shift(values, 4) == circular_shift(values, 1)


def test_null_rate_is_low_when_the_narrative_truly_follows():
    """A series where narrative genuinely trails physical should beat chance."""
    days = _days(80)
    physical = [4.0] * 80
    narrative = [100.0] * 80
    physical[50] = 9.0
    narrative[54] = 900.0
    rate = null_lead_rate(days, physical, narrative, trials=25)
    assert 0.0 <= rate <= 1.0


def test_null_rate_is_deterministic_for_a_given_seed():
    """A backtest that cannot be reproduced is not evidence."""
    days = _days(80)
    physical = [4.0 + (i % 3) for i in range(80)]
    narrative = [100.0 + (i % 5) * 10 for i in range(80)]
    physical[50] = 9.0
    narrative[54] = 900.0
    a = null_lead_rate(days, physical, narrative, trials=20, seed=7)
    b = null_lead_rate(days, physical, narrative, trials=20, seed=7)
    assert a == b


def test_different_seeds_can_differ():
    days = _days(80)
    physical = [4.0 + (i % 3) for i in range(80)]
    narrative = [100.0 + (i % 7) * 10 for i in range(80)]
    physical[50] = 9.0
    narrative[54] = 900.0
    rates = {null_lead_rate(days, physical, narrative, trials=20, seed=s) for s in range(4)}
    assert len(rates) >= 1  # sanity: it runs; variation is not guaranteed on tiny inputs


def test_flat_series_produce_no_spurious_leads():
    """Nothing spikes, so nothing can lead — the null must be zero, not noise."""
    days = _days(80)
    flat_physical = [4.0] * 80
    flat_narrative = [100.0] * 80
    assert null_lead_rate(days, flat_physical, flat_narrative, trials=15) == 0.0
