"""Predictors layer — B0 random, B1 persistence, B2 base rate, B3-B5 single
domain, B6 composite.

Each returns {(country, month): score} for every panel cell it can score.
Scores at month t may use information from months <= t only.

B0-B2 return values in [0, 1]. The domain and composite predictors return the
panel's own z-scored signals, which are unbounded — AUROC and AUPR are rank
statistics, so only the ordering matters and no rescaling is needed.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any


def score_random(
    panel: Iterable[Mapping[str, Any]], *, seed: int
) -> dict[tuple[str, datetime], float]:
    """B0 — seeded uniform noise; the AUROC ≈ 0.5 sanity floor."""
    rng = random.Random(seed)
    return {(row["country"], row["month"]): rng.random() for row in panel}


def score_persistence(
    panel: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, datetime], float]:
    """B1 — this month's label as the forecast for the coming window."""
    return {(row["country"], row["month"]): float(row["label_any"]) for row in panel}


def score_base_rate(
    panel: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, datetime], float]:
    """B2 — expanding mean of label_any over the country's months <= t."""
    by_country: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
    for row in panel:
        by_country[row["country"]].append((row["month"], int(row["label_any"])))

    scores: dict[tuple[str, datetime], float] = {}
    for country, cells in by_country.items():
        cells.sort()
        running = 0
        for n, (month, label) in enumerate(cells, start=1):
            running += label
            scores[(country, month)] = running / n
    return scores


#: The domains a single-domain baseline may be built from, and the panel
#: column each one reads. Kept explicit so a typo raises instead of quietly
#: scoring nothing, which would drop a contender out of the race unnoticed.
DOMAIN_COLUMNS: dict[str, str] = {
    "market": "signal_market",
    "geopolitical": "signal_geopolitical",
    "hazard": "signal_hazard",
}


def score_domain(
    panel: Iterable[Mapping[str, Any]], *, domain: str
) -> dict[tuple[str, datetime], float]:
    """B3/B4/B5 — one domain's signal used alone as the forecast.

    These are the baselines the headline claim is actually defined against:
    the composite must beat each of them, not merely beat random. Without
    them the only comparison available was against the no-skill trio, which
    answers a different and much easier question.

    No new arithmetic is involved. The composite z-scores each domain before
    combining, and `app/panel/assemble.py` stores those components, so a
    single-domain baseline is the composite deprived of its other inputs —
    which is exactly the counterfactual the claim needs.

    Rows where the domain has no value are omitted rather than scored zero: a
    month with no market data is not a calm market month, and inventing a
    reading would answer the question with evidence that does not exist.
    """
    column = DOMAIN_COLUMNS.get(domain)
    if column is None:
        raise ValueError(f"unknown composite domain: {domain!r}")

    scores: dict[tuple[str, datetime], float] = {}
    for row in panel:
        value = row.get(column)
        if value is None:
            continue
        value = float(value)
        if value != value:  # NaN from pandas
            continue
        scores[(row["country"], row["month"])] = value
    return scores


def score_composite(
    panel: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, datetime], float]:
    """B6 — the composite stress index itself, where it has a value.

    Rows without a composite score (no signals collected/backfilled for that
    month) are omitted; evaluation must restrict every contender to this
    common support for a fair head-to-head.
    """
    scores: dict[tuple[str, datetime], float] = {}
    for row in panel:
        value = row.get("composite_score")
        if value is None:
            continue
        value = float(value)
        if value != value:  # NaN from pandas
            continue
        scores[(row["country"], row["month"])] = value
    return scores
