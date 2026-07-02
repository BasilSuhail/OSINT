"""Backtest orchestrator: registry → backfill → divergence → metrics → report."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.backtest.backfill import BackfillSource, GdeltBackfill, UsgsBackfill, backfill_event
from app.backtest.metrics import (
    EventLead,
    GateMetrics,
    false_positive_rate,
    lead_for_series,
    summarize,
)
from app.backtest.registry import load_registry
from app.backtest.report import render_report
from app.db import session_scope
from app.divergence.aggregate import daily_side_counts
from app.divergence.config import DIVERGENCE_METHOD_VERSION
from app.divergence.scoring import DivergenceSeries, compute_divergence_series, detect_lead

_LOOKBACK_DAYS = 45
_LOOKAHEAD_DAYS = 15


def run_backtest(
    session: Session,
    registry_path: str | Path,
    *,
    backfill: bool = True,
    sources: list[BackfillSource] | None = None,
) -> tuple[GateMetrics, list[EventLead], str]:
    """Run the phase-1 lead-time gate against a frozen event registry."""
    events, registry_hash = load_registry(str(registry_path))
    if sources is None:
        sources = [GdeltBackfill(), UsgsBackfill()]

    leads: list[EventLead] = []
    series_list: list[DivergenceSeries] = []
    narrative_days: set[date] = set()
    for event in events:
        if backfill:
            backfill_event(
                session,
                event,
                sources,
                lookback_days=_LOOKBACK_DAYS,
                lookahead_days=_LOOKAHEAD_DAYS,
            )
            session.commit()
        start = event.date - timedelta(days=_LOOKBACK_DAYS)
        end = event.date + timedelta(days=_LOOKAHEAD_DAYS)
        days, physical, narrative = daily_side_counts(session, event.country, start, end)
        series = compute_divergence_series(days, physical, narrative)
        series_list.append(series)
        lead = lead_for_series(event.id, series)
        leads.append(lead)
        narrative_day = detect_lead(series).narrative_spike_day
        if narrative_day is not None:
            narrative_days.add(narrative_day)

    fp_rate = false_positive_rate(series_list, narrative_days)
    metrics = summarize(leads, fp_rate=fp_rate)
    rendered = render_report(
        metrics,
        leads,
        registry_hash=registry_hash,
        method_version=DIVERGENCE_METHOD_VERSION,
    )
    return metrics, leads, rendered


def main() -> int:
    registry_path = Path("app/backtest/events.yaml")
    with session_scope() as session:
        metrics, _, rendered = run_backtest(session, registry_path, backfill=True)
    _, registry_hash = load_registry(registry_path)
    out = Path("docs/backtest") / f"{registry_hash[:8]}-report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered)
    print(f"verdict={metrics.verdict} report={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
