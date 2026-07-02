"""Tests for ``app.backtest.metrics`` gate score helpers."""

from __future__ import annotations

from datetime import date

from app.backtest.metrics import (
    EventLead,
    GateMetrics,
    false_positive_rate,
    lead_for_series,
    summarize,
)
from app.divergence.config import MAX_LEAD_LOOKBACK_DAYS
from app.divergence.scoring import DivergenceSeries


def test_summarize_passes_when_majority_lead() -> None:
    leads = [
        EventLead("a", 3),
        EventLead("b", 2),
        EventLead("c", None),
    ]
    metrics = summarize(leads, fp_rate=0.1)
    assert metrics == GateMetrics(
        median_lead=2.5,  # median of [2, 3] is 2.5
        pct_events_leading=2 / 3,
        n_events=3,
        false_positive_rate=0.1,
        verdict="PASS",
    )


def test_summarize_fails_when_minority_lead() -> None:
    leads = [EventLead("a", 3), EventLead("b", None), EventLead("c", None)]
    metrics = summarize(leads, fp_rate=0.1)
    assert metrics.verdict == "FAIL"
    assert metrics.pct_events_leading == 1 / 3


def test_false_positive_rate_scans_without_registry_hit() -> None:
    base = date(2025, 1, 1)
    series = DivergenceSeries(
        days=[base.replace(day=d) for d in range(1, 31)],
        physical_z=[0.0] * 29,
        narrative_z=[0.0] * 29,
        divergence=[0.0] * 29,
    )
    # Spike before narrative window and after it should count as false positives.
    spike_days = {base.replace(day=5), base.replace(day=30)}
    # inject physical spikes and keep corresponding narrative windows empty
    days = list(series.days)
    physical = [0.0 if d not in spike_days else 2.0 for d in days]
    with_spikes = DivergenceSeries(
        days=days,
        physical_z=physical,
        narrative_z=[0.0] * len(days),
        divergence=[0.0] * len(days),
    )
    fp = false_positive_rate([with_spikes], {base.replace(day=25)})
    assert fp == 0.5
    assert MAX_LEAD_LOOKBACK_DAYS == 21


def test_lead_for_series() -> None:
    series = DivergenceSeries(
        days=[date(2025, 1, d) for d in (1, 2, 3)],
        physical_z=[0.0, 2.5, 0.0],
        narrative_z=[0.0, 0.0, 2.0],
        divergence=[0.0, 2.5, -2.0],
    )
    assert lead_for_series("evt", series).lead_days == 1
