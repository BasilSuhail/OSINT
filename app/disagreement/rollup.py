"""(country-pair, month) roll-up of per-story divergence (WS-B step 3, #372).

Pure aggregation over persisted `story_disagreement` rows: for every country
pair inside a story, that pair's own distance (the `pairs` component) joins
the pair's month bucket, keyed by the story's first_seen month. Rows scored
before the `pairs` component existed are excluded rather than guessed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

PairKey = tuple[str, str, str]  # (country_a, country_b, month ISO date)


def aggregate_pairs(rows: Iterable[Mapping[str, Any]]) -> dict[PairKey, dict[str, Any]]:
    """rows: story_disagreement-shaped mappings — first_seen, components."""
    sums: dict[PairKey, list[float]] = {}
    for row in rows:
        pairs = (row.get("components") or {}).get("pairs")
        if not pairs:
            continue
        month = date(row["first_seen"].year, row["first_seen"].month, 1).isoformat()
        for pair, distance in pairs.items():
            country_a, country_b = pair.split("|", 1)
            sums.setdefault((country_a, country_b, month), []).append(distance)

    return {
        key: {"n_stories": len(values), "mean_divergence": sum(values) / len(values)}
        for key, values in sums.items()
    }
