"""Is a score carrying any information at all (#589)?

A predictor that returns the same number for every country is not making a
prediction. Recording one as a forecast pollutes the only out-of-sample evidence
this project has: 501 of 582 journal predictions carry the constant 0.5, because
the live composite z-scores to zero against a history retention has already
deleted (#586).

Written as a check rather than a feature flag, so it is self-healing. When the
underlying score varies again, callers resume with no code change.

Exact flatness was the original bar, and the data walked straight through it
(#831). In July 2026 the live composite took seven distinct values across 519
rows — 98.8% of them exactly 0.5 — so `min != max` held, the series passed, and
1,101 forecasts of a constant were recorded as forecasts. One country differing
by a rounding error made 518 identical rows look like a distribution.

The bar is now **concentration**: the share of observations taking the single
most common value. That statistic is not invented here — `app.audit.checks`
met the identical shape one layer over, a column nominally continuous that is
really a flag, and answered it the same way, because standard deviation alone
does not expose it. Both use one threshold, imported rather than repeated, so
the two cannot drift into disagreeing about whether a number carries
information.

Deciding whether a *spread* is large enough to be useful is still a modelling
question this does not answer. It answers the prior one: is there a spread, or
is there one number wearing a distribution.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Final

from app.audit.checks import MAX_CONTINUOUS_TOP_SHARE

#: Above this share on one value, a series is one number with noise on it.
#: Imported from the audit rather than restated: two thresholds for one shape
#: drift, and then two parts of the system disagree about whether a score
#: carries information (#831).
MAX_TOP_SHARE: Final[float] = MAX_CONTINUOUS_TOP_SHARE


def _values(scores: Iterable[float | None]) -> list[float]:
    return [float(score) for score in scores if score is not None]


def top_share(values: list[float]) -> float:
    """Share of observations taking the single most common value."""
    if not values:
        return 1.0
    _, most = Counter(values).most_common(1)[0]
    return most / len(values)


def is_degenerate(scores: Iterable[float | None]) -> bool:
    """True when the scores carry no cross-sectional information.

    Fewer than two observations counts as degenerate: a single country is not a
    cross-section, so there is nothing to rank it against.
    """
    values = _values(scores)
    if len(values) < 2:
        return True
    return top_share(values) > MAX_TOP_SHARE


def describe(scores: Iterable[float | None], *, label: str) -> str | None:
    """A one-line reason, or None when there is nothing to object to."""
    if not is_degenerate(scores):
        return None
    values = _values(scores)
    if not values:
        return f"{label}: no scores to read"
    if len(values) == 1:
        return f"{label}: a single observation ({values[0]}) is not a cross-section"
    share = top_share(values)
    modal = Counter(values).most_common(1)[0][0]
    if share == 1.0:
        return f"{label}: all {len(values):,} scores are {modal} — no variance to predict from"
    return (
        f"{label}: {share:.1%} of {len(values):,} scores are {modal} — a constant with noise "
        f"on it, not a prediction"
    )
