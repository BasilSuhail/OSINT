"""Stratified metrics for a country-demeaned score (#582).

Pure functions, no sklearn, matching `app.baselines.metrics`. Degenerate inputs
return None so callers report `n/a` rather than a fake number.

The composite z-scores within country, so it carries no cross-country level by
construction. A pooled AUROC therefore measures mostly which country a row
belongs to — and with 133 of 238 panel countries never labelled, that is most of
the metric. These functions compare a country's months only against that same
country's months.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from app.baselines.metrics import auroc

Row = Mapping[str, Any]
Statistic = Callable[[Sequence[Row]], float | None]


def _by_country(rows: Iterable[Row]) -> dict[str, list[Row]]:
    grouped: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[row["country"]].append(row)
    return grouped


def _split(rows: Sequence[Row]) -> tuple[list[float], list[float]]:
    positives = [float(r["score"]) for r in rows if int(r["target"]) == 1]
    negatives = [float(r["score"]) for r in rows if int(r["target"]) == 0]
    return positives, negatives


def within_country_concordance(rows: Sequence[Row]) -> float | None:
    """Primary metric — the stratified c-statistic.

    Over all (positive, negative) month pairs drawn from the same country, the
    fraction where the positive scores higher. Ties count 0.5. Countries weight
    by their pair count; a country missing either class contributes nothing,
    which is why the 133 never-labelled panel countries drop out entirely.

    Returns None when no country has both classes — no pairs, no statistic.

    Computed as a pair-weighted mean of per-country AUROC rather than by
    enumerating pairs. Identical by definition — AUROC is the tie-aware
    Mann-Whitney concordance, and weighting each country by its own pair count
    reconstructs the pooled ratio — but O(n log n) per country instead of
    O(P*N), which is what makes 1000 bootstrap resamples affordable.
    """
    concordant = 0.0
    pairs = 0
    for country_rows in _by_country(rows).values():
        positives, negatives = _split(country_rows)
        if not positives or not negatives:
            continue
        country_auroc = auroc(
            [float(r["score"]) for r in country_rows],
            [int(r["target"]) for r in country_rows],
        )
        if country_auroc is None:
            continue
        country_pairs = len(positives) * len(negatives)
        concordant += country_auroc * country_pairs
        pairs += country_pairs
    if not pairs:
        return None
    return concordant / pairs


def qualifying_countries(rows: Sequence[Row], *, min_per_class: int) -> int:
    """How many countries carry enough of both classes for their own AUROC."""
    return sum(
        1
        for country_rows in _by_country(rows).values()
        if _qualifies(country_rows, min_per_class=min_per_class)
    )


def _qualifies(country_rows: Sequence[Row], *, min_per_class: int) -> bool:
    positives, negatives = _split(country_rows)
    return len(positives) >= min_per_class and len(negatives) >= min_per_class


def mean_per_country_auroc(rows: Sequence[Row], *, min_per_class: int) -> float | None:
    """Secondary metric — unweighted mean of per-country AUROC.

    Equal weight per country rather than per pair. Secondary because the
    minimum-support rule discards countries the primary keeps, and a per-country
    AUROC over a handful of months is unstable.
    """
    scores: list[float] = []
    for country_rows in _by_country(rows).values():
        if not _qualifies(country_rows, min_per_class=min_per_class):
            continue
        value = auroc(
            [float(r["score"]) for r in country_rows],
            [int(r["target"]) for r in country_rows],
        )
        if value is not None:
            scores.append(value)
    if not scores:
        return None
    return sum(scores) / len(scores)


def bootstrap_ci(
    rows: Sequence[Row],
    statistic: Statistic,
    *,
    resamples: int,
    seed: int,
    alpha: float = 0.05,
) -> tuple[float | None, float | None]:
    """95% percentile CI, resampling **countries** with replacement.

    The country is the unit of independence: months within one country share its
    history and conflict dynamics, so resampling rows would treat correlated
    observations as independent and understate the interval.
    """
    if statistic(rows) is None:
        return None, None

    grouped = _by_country(rows)
    names = sorted(grouped)
    rng = random.Random(seed)

    estimates: list[float] = []
    for _ in range(resamples):
        drawn: list[Row] = []
        for _ in names:
            drawn.extend(grouped[names[rng.randrange(len(names))]])
        value = statistic(drawn)
        if value is not None:
            estimates.append(value)

    if not estimates:
        return None, None
    estimates.sort()
    low = estimates[max(0, int(alpha / 2 * len(estimates)) - 1)]
    high = estimates[min(len(estimates) - 1, int((1 - alpha / 2) * len(estimates)))]
    return low, high
