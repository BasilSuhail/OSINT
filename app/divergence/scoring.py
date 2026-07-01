"""Pure divergence scoring — no DB, no network."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date

from app.divergence.config import (
    DIVERGENCE_METHOD_VERSION,
    LOG_CEILING_NARRATIVE,
    LOG_CEILING_PHYSICAL,
    MAX_LEAD_LOOKBACK_DAYS,
    ROLLING_WINDOW_DAYS,
    TAU_N,
    TAU_P,
)


def _log_scale(raw: float, ceiling: float) -> float:
    """Log-dampen a non-negative count.

    ``ceiling`` defines the count that reads as "fully saturated."
    """
    if raw <= 0.0 or ceiling <= 0.0:
        return 0.0
    return math.log1p(raw) / math.log1p(ceiling)


@dataclass(frozen=True)
class DivergenceSeries:
    """Rolling-z divergence components for one country over aligned days."""

    days: list[date]
    physical_z: list[float]
    narrative_z: list[float]
    divergence: list[float]
    method_version: str = DIVERGENCE_METHOD_VERSION


@dataclass(frozen=True)
class LeadResult:
    """Detected lead relationship between physical and narrative spikes."""

    physical_spike_day: date | None
    narrative_spike_day: date | None
    lead_days: int | None


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


def compute_divergence_series(
    days: list[date], physical_raw: list[float], narrative_raw: list[float]
) -> DivergenceSeries:
    """Compute aligned rolling z-score series + divergence for one country."""
    if not (len(days) == len(physical_raw) == len(narrative_raw)):
        raise ValueError("days, physical_raw, narrative_raw must be equal length")
    physical_scaled = [_log_scale(v, LOG_CEILING_PHYSICAL) for v in physical_raw]
    narrative_scaled = [_log_scale(v, LOG_CEILING_NARRATIVE) for v in narrative_raw]
    physical_z = rolling_z(physical_scaled, ROLLING_WINDOW_DAYS)
    narrative_z = rolling_z(narrative_scaled, ROLLING_WINDOW_DAYS)
    divergence = [p - n for p, n in zip(physical_z, narrative_z, strict=True)]
    return DivergenceSeries(
        days=days,
        physical_z=physical_z,
        narrative_z=narrative_z,
        divergence=divergence,
    )


def detect_lead(series: DivergenceSeries) -> LeadResult:
    """Find the first narrative spike and nearest prior physical spike."""
    n_idx = next((i for i, z in enumerate(series.narrative_z) if z >= TAU_N), None)
    if n_idx is None:
        return LeadResult(physical_spike_day=None, narrative_spike_day=None, lead_days=None)
    narrative_day = series.days[n_idx]
    p_idx = next(
        (
            i
            for i in range(
                n_idx - 1, max(-1, n_idx - MAX_LEAD_LOOKBACK_DAYS) - 1, -1
            )
            if series.physical_z[i] >= TAU_P
        ),
        None,
    )
    if p_idx is None:
        return LeadResult(physical_spike_day=None, narrative_spike_day=narrative_day, lead_days=None)
    physical_day = series.days[p_idx]
    return LeadResult(
        physical_spike_day=physical_day,
        narrative_spike_day=narrative_day,
        lead_days=(narrative_day - physical_day).days,
    )
