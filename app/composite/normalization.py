"""Normalization layer — rolling z-score per (country, domain) time series.

JRC handbook normalisation step. We z-score each domain's raw severity time
series *within each country* over a rolling history window: each month's value
becomes (value - mean_history) / std_history.

Within-country normalisation matters because severity scales differ across
countries (a high-volatility market shifts the country's baseline). The
composite worker should react to *deviation from a country's own past*, not
to an absolute level.
"""

from __future__ import annotations

import math
from datetime import datetime

#: Default rolling history length (months) used when no override is provided.
DEFAULT_WINDOW_MONTHS: int = 12

#: Minimum number of historical observations needed to produce a non-zero
#: z-score. With fewer points the standard deviation is not meaningful and we
#: emit 0 so the composite does not react to noise on a cold start.
MIN_HISTORY: int = 3

#: Floating-point tolerance below which a standard deviation is treated as
#: zero. Without this, constant-value histories like [0.1] * 12 surface a
#: spurious sub-1e-15 std that produces meaningless huge z-scores.
STD_TOLERANCE: float = 1e-9


def _mean_std(values: list[float]) -> tuple[float, float]:
    """Return population mean and population standard deviation."""
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return mean, math.sqrt(variance)


def rolling_zscore(values: list[float], *, window: int = DEFAULT_WINDOW_MONTHS) -> list[float]:
    """Return per-position z-score against the preceding `window` values.

    The score at position i uses values[max(0, i - window):i] as history.
    Cold starts (i < MIN_HISTORY) and zero-variance windows emit 0.0.
    """
    if window <= 0:
        raise ValueError("window must be positive")
    out: list[float] = []
    for i, current in enumerate(values):
        history = values[max(0, i - window) : i]
        if len(history) < MIN_HISTORY:
            out.append(0.0)
            continue
        mean, std = _mean_std(history)
        if std < STD_TOLERANCE:
            out.append(0.0)
            continue
        out.append((current - mean) / std)
    return out


def normalize_domain_signals(
    buckets: dict[tuple[str, datetime], dict[str, float]],
    *,
    window: int = DEFAULT_WINDOW_MONTHS,
) -> dict[tuple[str, datetime], dict[str, float]]:
    """Apply rolling z-score per (country, domain) time series.

    Input: the dict returned by `aggregate_events_to_domain_signals`.
    Output: same shape, with each domain's value replaced by its z-score.
    """
    # Pivot to (country, domain) → sorted list of (bucket_start, value).
    series: dict[tuple[str, str], list[tuple[datetime, float]]] = {}
    for (country, bucket_start), domain_values in buckets.items():
        for domain, value in domain_values.items():
            series.setdefault((country, domain), []).append((bucket_start, value))

    # z-score each series in chronological order.
    z_lookup: dict[tuple[str, datetime, str], float] = {}
    for (country, domain), pairs in series.items():
        pairs.sort(key=lambda item: item[0])
        values = [v for _, v in pairs]
        zs = rolling_zscore(values, window=window)
        for (bucket_start, _), z in zip(pairs, zs, strict=True):
            z_lookup[(country, bucket_start, domain)] = z

    # Rebuild the input shape with z-scored values.
    normalized: dict[tuple[str, datetime], dict[str, float]] = {}
    for (country, bucket_start), domain_values in buckets.items():
        out: dict[str, float] = {}
        for domain in domain_values:
            out[domain] = z_lookup[(country, bucket_start, domain)]
        normalized[(country, bucket_start)] = out
    return normalized
