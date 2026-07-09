"""Rank layer — univariate AUROC/AUPR per indicator, ranked (WS-F, #376).

Each indicator takes the same exam the composite took: pre-registered eval
window, horizon targets from `app.baselines.targets`, metrics from
`app.baselines.metrics`. Two declared variants per indicator: raw (the number
as displayed) and abs (its magnitude — deviation signals are two-sided). No
Brier: z-scores are not probabilities, and pretending otherwise would fake a
calibration claim.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from app.baselines.metrics import aupr, auroc
from app.baselines.targets import build_targets

VARIANTS: tuple[str, ...] = ("raw", "abs")


def rank_indicators(
    panel: Iterable[Mapping[str, Any]],
    *,
    indicators: Sequence[str],
    horizons: Sequence[int],
    eval_start: datetime,
    eval_end: datetime,
) -> list[dict[str, Any]]:
    """One row per (indicator, variant, horizon), AUROC-descending per horizon.

    Support is per indicator: every eval-window row where the indicator has a
    value and the full target window is covered. Cross-indicator common
    support is the caller's second pass (see run.py).
    """
    panel = list(panel)
    results: list[dict[str, Any]] = []

    for horizon in horizons:
        targets = build_targets(panel, horizon=horizon)
        for indicator in indicators:
            values = {
                (row["country"], row["month"]): float(row[indicator])
                for row in panel
                if row.get(indicator) is not None
            }
            keys = sorted(
                key for key in targets if key in values and eval_start <= key[1] <= eval_end
            )
            y = [targets[key] for key in keys]
            for variant in VARIANTS:
                scores = [values[key] if variant == "raw" else abs(values[key]) for key in keys]
                results.append(
                    {
                        "indicator": indicator,
                        "variant": variant,
                        "horizon_months": horizon,
                        "n": len(y),
                        "positive_rate": round(sum(y) / len(y), 4) if y else None,
                        "auroc": auroc(scores, y),
                        "aupr": aupr(scores, y),
                    }
                )

    results.sort(
        key=lambda row: (
            row["horizon_months"],
            -(row["auroc"] if row["auroc"] is not None else -1.0),
            row["indicator"],
            row["variant"],
        )
    )
    return results
