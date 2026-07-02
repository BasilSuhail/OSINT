"""Targets layer — panel records → horizon targets.

Target for (country, t, k): 1 if any month in [t+1, t+k] has label_any = 1.
A row only qualifies when every month of the window exists in that country's
panel coverage — truncated horizons would silently bias targets negative.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any


def _add_months(month: datetime, n: int) -> datetime:
    total = month.year * 12 + (month.month - 1) + n
    return month.replace(year=total // 12, month=total % 12 + 1)


def build_targets(
    panel: Iterable[Mapping[str, Any]], *, horizon: int
) -> dict[tuple[str, datetime], int]:
    """Return {(country, month): 0/1} for rows whose full window is covered."""
    labels: dict[tuple[str, datetime], int] = {
        (row["country"], row["month"]): int(row["label_any"]) for row in panel
    }

    targets: dict[tuple[str, datetime], int] = {}
    for country, month in labels:
        window = [(country, _add_months(month, offset)) for offset in range(1, horizon + 1)]
        if any(key not in labels for key in window):
            continue
        targets[(country, month)] = int(any(labels[key] for key in window))
    return targets
