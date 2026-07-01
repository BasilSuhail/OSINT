"""Pure divergence scoring — no DB, no network."""

from __future__ import annotations

import math
import statistics


def rolling_z(values: list[float], window: int) -> list[float]:
    """Standardized anomaly per point vs trailing `window` prior points.

    For index i:
        z[i] = (values[i] - mean(prev)) / stdev(prev)
    where prev is up to the last `window` values strictly before i.

    Returns 0.0 for warmup (< 2 prior points) or zero-variance prior windows
    to avoid NaN/inf and keep the series numerically stable.
    """
    out: list[float] = []
    for i, v in enumerate(values):
        prev = values[max(0, i - window) : i]
        if len(prev) < 2:
            out.append(0.0)
            continue
        mean = statistics.fmean(prev)
        std = statistics.pstdev(prev)
        if std == 0.0:
            out.append(0.0)
            continue
        z = (v - mean) / std
        out.append(0.0 if math.isnan(z) else z)
    return out
