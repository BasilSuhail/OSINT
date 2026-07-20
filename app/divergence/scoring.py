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
    where prev is the last `window` values strictly before i.

    Returns 0.0 until a FULL baseline exists, and for zero-variance prior
    windows, to avoid NaN/inf and keep the series numerically stable.

    The full-baseline requirement is not fastidiousness (#526). Scoring from two
    prior points gave their near-zero standard deviation the last word, so an
    ordinary day read as 3-5 sigma; since `detect_lead` takes the FIRST spike it
    locked onto that phantom every time. Three unrelated events in the lead-time
    gate — Japan, Indonesia, Venezuela — all reported an identical -58 day lead
    from exactly this, and the run's headline median was three copies of it.
    """
    out: list[float] = []
    for i, v in enumerate(values):
        prev = values[max(0, i - window) : i]
        if len(prev) < window:
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


def detect_lead(
    series: DivergenceSeries,
    *,
    tau_physical: float | None = None,
    tau_narrative: float | None = None,
) -> LeadResult:
    """Find the first narrative spike and the nearest physical spike either side.

    Searches symmetrically on purpose (#544). Looking only backward meant a
    positive lead was the only result the detector could produce: in spiky,
    autocorrelated series some prior physical spike is nearly always inside the
    lookback, so it reported "sensors led" whenever it reported anything, and
    the case the claim must be tested against — coverage moving first — was
    invisible.

    That bias is why the v3 run produced nine leads, all positive, at exactly
    the rate a rotated control produced them.

    A positive lead means the physical spike came first; negative means the
    narrative did.
    """
    # Thresholds default to the frozen config values; they are overridable so
    # the result can be swept across thresholds without editing frozen
    # parameters (#548). A finding that holds only at TAU=1.5 is an artefact of
    # TAU=1.5, and there is no way to know which without varying it.
    tau_p = TAU_P if tau_physical is None else tau_physical
    tau_n = TAU_N if tau_narrative is None else tau_narrative
    n_idx = next((i for i, z in enumerate(series.narrative_z) if z >= tau_n), None)
    if n_idx is None:
        return LeadResult(
            physical_spike_day=None,
            narrative_spike_day=None,
            lead_days=None,
        )
    narrative_day = series.days[n_idx]
    # Nearest physical spike on either side, ties going to the earlier one so a
    # simultaneous pair still reads as "physical first" rather than flipping on
    # floating-point noise.
    candidates = [
        i
        for i in range(
            max(0, n_idx - MAX_LEAD_LOOKBACK_DAYS),
            min(len(series.days), n_idx + MAX_LEAD_LOOKBACK_DAYS + 1),
        )
        if i != n_idx and series.physical_z[i] >= tau_p
    ]
    p_idx = min(candidates, key=lambda i: (abs(i - n_idx), i)) if candidates else None
    if p_idx is None:
        return LeadResult(
            physical_spike_day=None,
            narrative_spike_day=narrative_day,
            lead_days=None,
        )
    physical_day = series.days[p_idx]
    return LeadResult(
        physical_spike_day=physical_day,
        narrative_spike_day=narrative_day,
        lead_days=(narrative_day - physical_day).days,
    )
