"""Scoreboard layer — prediction rows → per source x horizon track record."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


def build_scoreboard(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate issued/graded/pending counts, positive rate, Brier, mean score."""
    groups: dict[tuple[str, str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["source"], row["method_version"], row["horizon_months"])].append(row)

    lines: list[dict[str, Any]] = []
    for (source, version, horizon), members in sorted(groups.items()):
        graded = [m for m in members if m["outcome"] is not None]
        lines.append(
            {
                "source": source,
                "method_version": version,
                "horizon_months": horizon,
                "issued": len(members),
                "graded": len(graded),
                "pending": len(members) - len(graded),
                "positive_rate": (
                    sum(m["outcome"] for m in graded) / len(graded) if graded else None
                ),
                "mean_score": (sum(m["score"] for m in graded) / len(graded) if graded else None),
                "brier": (
                    sum((m["score"] - m["outcome"]) ** 2 for m in graded) / len(graded)
                    if graded
                    else None
                ),
            }
        )
    return lines
