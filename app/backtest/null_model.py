"""Permutation baseline for the lead-time gate (#538).

The gate reports a share of events where a physical spike preceded a narrative
spike, and passes when that share clears 50%. Nothing established what 50% was
worth. Both series are spiky and autocorrelated, and two such series produce
apparent leads at some rate purely by chance — so the observed rate is
uninterpretable until the chance rate is measured on the same data.

The baseline keeps each event's physical series exactly as it is and rotates its
narrative series, then re-runs the same detector. Rotation destroys the temporal
relationship between the two sides while preserving everything else about the
narrative series: its values, its variance, and crucially its autocorrelation. A
free shuffle would scatter the runs of consecutive busy days that make a spike
detectable at all, producing an implausibly low null and flattering the result.

Reported beside the observed rate, this turns "64% of events led" into "64%
against a chance rate of X%", which is a claim that can be examined.
"""

from __future__ import annotations

import random
from datetime import date

from app.divergence.config import MAX_LEAD_LOOKBACK_DAYS
from app.divergence.scoring import compute_divergence_series, detect_lead

#: Rotations smaller than this leave the two series nearly aligned, so a
#: "shuffled" run would still contain the real relationship and the null would
#: be biased upward — toward finding leads that the true data also finds.
MIN_SHIFT_DAYS = MAX_LEAD_LOOKBACK_DAYS + 1

DEFAULT_TRIALS = 200


def circular_shift(values: list[float], shift: int) -> list[float]:
    """Rotate a series, wrapping the tail around to the front.

    Rotation rather than `random.shuffle` on purpose: it preserves the ordering
    of neighbouring days, so runs of quiet and busy days survive intact and the
    detector still has the same kind of series to work on.
    """
    if not values:
        return []
    offset = shift % len(values)
    if offset == 0:
        return list(values)
    return values[-offset:] + values[:-offset]


def null_lead_rate(
    days: list[date],
    physical: list[float],
    narrative: list[float],
    *,
    trials: int = DEFAULT_TRIALS,
    min_lead_days: int = 1,
    seed: int | None = 0,
) -> float:
    """Share of rotated runs in which the physical side appears to lead.

    Deterministic by default: a backtest whose baseline moves between runs is
    not evidence, so the seed is fixed unless a caller asks otherwise.
    """
    if not days or trials <= 0:
        return 0.0

    span = len(days)
    usable = span - MIN_SHIFT_DAYS
    if usable <= MIN_SHIFT_DAYS:
        # Too short to rotate meaningfully without either leaving the series
        # nearly aligned or wrapping back to alignment from the other side.
        return 0.0

    rng = random.Random(seed)
    leads = 0
    for _ in range(trials):
        shift = rng.randint(MIN_SHIFT_DAYS, usable)
        rotated = circular_shift(narrative, shift)
        series = compute_divergence_series(days, physical, rotated)
        result = detect_lead(series)
        if result.lead_days is not None and result.lead_days >= min_lead_days:
            leads += 1
    return leads / trials
