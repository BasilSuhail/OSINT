"""Eligibility layer — calm-window onset filtering (#380, docs/onset-eval.md).

(country, t) is onset-eligible iff every one of the preceding `calm_months`
months exists in the country's panel and carries label_any = 0. Missing
history is not calm: a month whose calm window reaches before the country's
coverage is excluded, never assumed quiet.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from app.baselines.targets import _add_months


def onset_eligible(
    panel: Iterable[Mapping[str, Any]], *, calm_months: int
) -> set[tuple[str, datetime]]:
    labels: dict[tuple[str, datetime], int] = {
        (row["country"], row["month"]): int(row["label_any"]) for row in panel
    }
    eligible: set[tuple[str, datetime]] = set()
    for country, month in labels:
        window = [(country, _add_months(month, -offset)) for offset in range(1, calm_months + 1)]
        if any(key not in labels for key in window):
            continue
        if any(labels[key] for key in window):
            continue
        eligible.add((country, month))
    return eligible
