"""Tests for backtest report markdown rendering."""

from __future__ import annotations

from app.backtest.metrics import EventLead, GateMetrics
from app.backtest.report import render_report


def test_report_states_verdict_and_events() -> None:
    metrics = GateMetrics(
        median_lead=2.0,
        pct_events_leading=0.66,
        n_events=3,
        false_positive_rate=0.1,
        verdict="PASS",
    )
    leads = [EventLead("nato-quake", 3), EventLead("x", None)]
    md = render_report(metrics, leads, registry_hash="abc123def456", method_version="div.v1")
    assert "PASS" in md
    assert "nato-quake" in md
    assert "div.v1" in md
    assert "abc123de" in md
