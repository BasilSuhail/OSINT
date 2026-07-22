"""Is a score carrying any information at all (#589)?

A predictor that returns the same number for every country is not making a
prediction. Recording one as a forecast pollutes the only out-of-sample evidence
this project has: 501 of 582 journal predictions carry the constant 0.5, because
the live composite z-scores to zero against a history retention has already
deleted (#586).

Written as a check rather than a feature flag, so it is self-healing. When the
underlying score varies again, callers resume with no code change.

Only *exact* flatness is refused. Deciding whether a spread is large enough to be
useful is a modelling question; this answers the prior one — is there any spread.
"""

from __future__ import annotations

from collections.abc import Iterable


def _values(scores: Iterable[float | None]) -> list[float]:
    return [float(score) for score in scores if score is not None]


def is_degenerate(scores: Iterable[float | None]) -> bool:
    """True when the scores carry no cross-sectional information.

    Fewer than two observations counts as degenerate: a single country is not a
    cross-section, so there is nothing to rank it against.
    """
    values = _values(scores)
    if len(values) < 2:
        return True
    return min(values) == max(values)


def describe(scores: Iterable[float | None], *, label: str) -> str | None:
    """A one-line reason, or None when there is nothing to object to."""
    if not is_degenerate(scores):
        return None
    values = _values(scores)
    if not values:
        return f"{label}: no scores to read"
    if len(values) == 1:
        return f"{label}: a single observation ({values[0]}) is not a cross-section"
    return f"{label}: all {len(values):,} scores are {values[0]} — no variance to predict from"
