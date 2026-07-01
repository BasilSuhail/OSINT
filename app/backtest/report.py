"""Render the gate backtest as a markdown report."""

from __future__ import annotations

from app.backtest.metrics import EventLead, GateMetrics


def render_report(
    metrics: GateMetrics,
    leads: list[EventLead],
    *,
    registry_hash: str,
    method_version: str,
) -> str:
    """Render a compact markdown audit artifact for issue #250."""
    median = "n/a" if metrics.median_lead is None else f"{metrics.median_lead:.1f} days"
    lines: list[str] = [
        f"# Divergence Lead-Time Gate — {metrics.verdict}",
        "",
        f"- Method version: `{method_version}`",
        f"- Registry hash: `{registry_hash[:8]}`",
        f"- Events: {metrics.n_events}",
        f"- Median physical lead: {median}",
        f"- Events leading ≥ 1 day: {metrics.pct_events_leading:.0%}",
        f"- False-positive rate: {metrics.false_positive_rate:.0%}",
        "",
        "## Per-event lead",
        "",
        "| event | lead (days) |",
        "|---|---|",
    ]
    for lead in leads:
        lines.append(f"| {lead.event_id} | {'—' if lead.lead_days is None else lead.lead_days} |")
    return "\n".join(lines) + "\n"
