"""Gate metrics: lead distribution + false-positive rate + PASS/FAIL."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

from app.divergence.config import MAX_LEAD_LOOKBACK_DAYS, TAU_P
from app.divergence.scoring import DivergenceSeries, detect_lead

#: Frozen pass bar for the phase-1 gate. Public because the report prints it:
#: an artifact that states a verdict without stating the bar it was judged
#: against cannot be checked by anyone reading it later (#524).
MIN_LEAD_DAYS = 1
MAJORITY_SHARE = 0.5


@dataclass(frozen=True)
class EventLead:
    event_id: str
    lead_days: int | None


@dataclass(frozen=True)
class GateMetrics:
    median_lead: float | None
    pct_events_leading: float
    n_events: int
    false_positive_rate: float
    verdict: str


def lead_for_series(event_id: str, series: DivergenceSeries) -> EventLead:
    """Produce an event lead record from one divergence series."""
    return EventLead(event_id=event_id, lead_days=detect_lead(series).lead_days)


def false_positive_rate(
    series_list: list[DivergenceSeries],
    registry_narrative_days: set[date],
) -> float:
    """Fraction of physical spikes with no registry narrative spike nearby."""
    total = 0
    false = 0
    for series in series_list:
        for idx, z in enumerate(series.physical_z):
            if z < TAU_P:
                continue
            total += 1
            day = series.days[idx]
            near = any(
                0 <= (n_day - day).days <= MAX_LEAD_LOOKBACK_DAYS
                for n_day in registry_narrative_days
            )
            if not near:
                false += 1
    return false / total if total else 0.0


def summarize(leads: list[EventLead], fp_rate: float) -> GateMetrics:
    """Apply the frozen pass bar to per-event lead decisions."""
    valid_leads = [lead.lead_days for lead in leads if lead.lead_days is not None]
    leading = [lead for lead in valid_leads if lead >= MIN_LEAD_DAYS]
    n_events = len(leads)
    pct_events_leading = len(leading) / n_events if n_events else 0.0
    median_lead = statistics.median(valid_leads) if valid_leads else None
    passes = (
        median_lead is not None
        and median_lead >= MIN_LEAD_DAYS
        and pct_events_leading > MAJORITY_SHARE
    )
    return GateMetrics(
        median_lead=median_lead,
        pct_events_leading=pct_events_leading,
        n_events=n_events,
        false_positive_rate=fp_rate,
        verdict="PASS" if passes else "FAIL",
    )
