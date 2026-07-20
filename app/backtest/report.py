"""Render the gate backtest as a markdown report.

This file is the artifact a thesis appendix quotes, so it has to survive being
read six months later by someone who did not run it. The first real run
reported "Events: 8" with a median lead of -27 days; only two of those eight
produced a lead value at all, so the headline number was the midpoint of two
measurements, and nothing in the report said so (#524).
"""

from __future__ import annotations

import statistics

from app.backtest.metrics import MAJORITY_SHARE, MIN_LEAD_DAYS, EventLead, GateMetrics

#: Below this many measured leads the median is an anecdote, not a statistic.
MIN_CREDIBLE_LEADS = 8


def render_report(
    metrics: GateMetrics,
    leads: list[EventLead],
    *,
    registry_hash: str,
    method_version: str,
    registry_size: int | None = None,
    unscorable: list[tuple[str, str]] | None = None,
    null_rate: float | None = None,
    null_leads: list[int] | None = None,
    p_value: float | None = None,
) -> str:
    """Render a markdown audit artifact for the lead-time gate."""
    unscorable = unscorable or []
    measured = [lead for lead in leads if lead.lead_days is not None]
    median = "n/a" if metrics.median_lead is None else f"{metrics.median_lead:.1f} days"
    size = registry_size if registry_size is not None else metrics.n_events

    lines: list[str] = [
        f"# Divergence Lead-Time Gate — {metrics.verdict}",
        "",
        f"- Method version: `{method_version}`",
        f"- Registry hash: `{registry_hash[:8]}`",
        f"- Pass bar: median lead ≥ {MIN_LEAD_DAYS} day "
        f"AND more than {MAJORITY_SHARE:.0%} of events leading",
        "",
        "## Sample",
        "",
        f"- Registry events: {size}",
        f"- Scored (narrative series available): {metrics.n_events}",
        f"- Produced a lead measurement: {len(measured)}",
        f"- Excluded as unscorable: {len(unscorable)}",
        "",
        "## Result",
        "",
        f"- Median physical lead: {median}",
        f"- Events leading ≥ {MIN_LEAD_DAYS} day: {metrics.pct_events_leading:.0%}",
        f"- False-positive rate: {metrics.false_positive_rate:.0%}",
    ]

    if null_rate is not None:
        observed = metrics.pct_events_leading
        lines += [
            f"- **Chance rate (narrative series rotated): {null_rate:.0%}**",
            f"- Observed minus chance: {observed - null_rate:+.0%}",
            "",
            (
                f"- Null median lead: {statistics.median(null_leads):+.1f} days"
                if null_leads
                else "- Null median lead: n/a"
            ),
            (
                f"- **Permutation p-value: {p_value:.3f}** — share of chance runs "
                "producing a lead at least this long"
                if p_value is not None
                else ""
            ),
            "",
            "The chance rate re-runs the same detector with each event's narrative "
            "series rotated, which breaks its timing against the physical side "
            "while preserving its values and autocorrelation. A pass rate only "
            "means something measured against it.",
        ]

    if len(measured) < MIN_CREDIBLE_LEADS:
        lines += [
            "",
            f"> **Caution — the measured sample is too small to interpret.** "
            f"The median above is computed over {len(measured)} lead "
            f"measurement(s), not over {size} registry events. A median of two "
            f"numbers is not a distribution, and a lead landing at the edge of "
            f"the 60-day window is more likely detector boundary behaviour than "
            f"signal. Treat this run as a pipeline check, not as evidence for or "
            f"against the claim.",
        ]

    lines += ["", "## Per-event lead", "", "| event | lead (days) |", "|---|---|"]
    for lead in leads:
        lines.append(f"| {lead.event_id} | {'—' if lead.lead_days is None else lead.lead_days} |")

    if unscorable:
        lines += [
            "",
            "## Excluded (no narrative series)",
            "",
            "These events were not counted in either direction. A fetch failure "
            "is not evidence against the claim.",
            "",
            "| event | reason |",
            "|---|---|",
        ]
        for event_id, reason in unscorable:
            lines.append(f"| {event_id} | {reason} |")

    return "\n".join(lines) + "\n"
