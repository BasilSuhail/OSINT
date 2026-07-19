"""Backtest orchestrator: registry → backfill → divergence → metrics → report."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.backtest.backfill import BackfillSource, UsgsBackfill, backfill_event
from app.backtest.metrics import (
    EventLead,
    GateMetrics,
    false_positive_rate,
    lead_for_series,
    summarize,
)
from app.backtest.narrative import (
    DEFAULT_CACHE_DIR,
    NarrativeUnavailableError,
    daily_series,
    fetch_daily_volume,
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
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
    volume_fetcher: Callable[..., dict[date, int]] | None = None,
) -> tuple[GateMetrics, list[EventLead], str, list[tuple[str, str]]]:
    """Run the phase-1 lead-time gate against a frozen event registry.

    Returns the metrics, the per-event leads, the rendered report, and the
    events that could not be scored at all — kept separate so a fetch failure
    is never counted as evidence against the claim.
    """
    events, registry_hash = load_registry(str(registry_path))
    if sources is None:
        # Only the physical side is backfilled now: narrative volume comes from
        # the GDELT timeline rather than from stored article rows (#518).
        sources = [UsgsBackfill()]

    # Injectable so tests and offline reruns never touch a rate-limited API.
    fetch_volume = volume_fetcher or fetch_daily_volume
    unscorable: list[tuple[str, str]] = []
    leads: list[EventLead] = []
    series_list: list[DivergenceSeries] = []
    narrative_days: set[date] = set()
    for event in events:
        if backfill:
            backfill_event(
                session,
                event,
                sources,
                # The gate re-runs constantly; refetching stored windows cost
                # ~5 minutes an event and made a rerun a 90-minute wait (#522).
                skip_if_covered=True,
                lookback_days=_LOOKBACK_DAYS,
                lookahead_days=_LOOKAHEAD_DAYS,
            )
            session.commit()
        start = event.date - timedelta(days=_LOOKBACK_DAYS)
        end = event.date + timedelta(days=_LOOKAHEAD_DAYS)
        # Physical side from our own sensor rows; narrative side from GDELT's
        # daily volume timeline (#518). Counting local gdelt rows gave a series
        # of near-zeros — the live feed holds ~2 weeks, while a window is 60
        # days — so every event scored "no narrative spike" and the gate failed
        # on missing data rather than on evidence.
        days, physical, _unused_local_narrative = daily_side_counts(
            session, event.country, start, end
        )
        try:
            volume = fetch_volume(event.country, start, end, cache_dir=cache_dir)
        except NarrativeUnavailableError as exc:
            # Unscorable, not negative. Counting it as "no lead" would let a
            # fetch failure masquerade as a refutation of the claim.
            unscorable.append((event.id, str(exc)))
            continue
        _, narrative_counts = daily_series(volume, start, end)
        series = compute_divergence_series(days, physical, narrative_counts)
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
    return metrics, leads, rendered, unscorable


def main() -> int:
    registry_path = Path("app/backtest/events.yaml")
    with session_scope() as session:
        metrics, _, rendered, unscorable = run_backtest(session, registry_path, backfill=True)
    _, registry_hash = load_registry(registry_path)
    out = Path("docs/backtest") / f"{registry_hash[:8]}-report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered)
    print(f"verdict={metrics.verdict} scored={metrics.n_events} report={out}")
    for event_id, reason in unscorable:
        print(f"  UNSCORABLE {event_id}: {reason}")
    if unscorable:
        print(
            f"  {len(unscorable)} event(s) had no narrative series. "
            "They are excluded, not counted as failures."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
