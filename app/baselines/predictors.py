"""Predictors layer — B0 random, B1 persistence, B2 expanding base rate.

Each returns {(country, month): score in [0, 1]} for every panel cell. Scores
at month t may use information from months <= t only.
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
