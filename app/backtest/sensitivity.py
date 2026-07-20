"""Sweep the lead-time gate across spike thresholds (#548).

A result that holds only at TAU=1.5 is a property of TAU=1.5, and there is no
way to tell which without varying it. The gate's frozen thresholds are a
pre-registered choice, not a discovered one, so the honest question is whether
the conclusion survives other reasonable choices.

Reads only cached narrative windows, so a sweep costs no API calls and can be
re-run freely — which is the point of a robustness check nobody wants to wait an
hour for.
"""

from __future__ import annotations

import argparse
import statistics
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from app.backtest.narrative import (
    NarrativeUnavailableError,
    daily_series,
    fetch_daily_volume,
)
from app.backtest.null_model import null_lead_distribution
from app.backtest.registry import load_registry
from app.db import session_scope
from app.divergence.aggregate import daily_physical_intensity
from app.divergence.config import ROLLING_WINDOW_DAYS
from app.divergence.scoring import compute_divergence_series, detect_lead

#: Mirrors app.backtest.run: the warmup sits in addition to the analysed span.
_ANALYSIS_LOOKBACK_DAYS = 45
_LOOKBACK_DAYS = _ANALYSIS_LOOKBACK_DAYS + ROLLING_WINDOW_DAYS
_LOOKAHEAD_DAYS = 15

DEFAULT_THRESHOLDS = (1.0, 1.25, 1.5, 2.0, 2.5)
DEFAULT_TRIALS = 60


@dataclass(frozen=True)
class ThresholdResult:
    tau: float
    measured: int
    observed_median: float | None
    null_median: float | None
    observed_lead_share: float
    null_lead_share: float
    p_value: float


def sweep(
    registry_path: str | Path = "app/backtest/events.yaml",
    *,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    trials: int = DEFAULT_TRIALS,
) -> list[ThresholdResult]:
    """Run the gate at each threshold over the cached windows."""
    events, _ = load_registry(str(registry_path))
    results: list[ThresholdResult] = []

    with session_scope() as session:
        windows = []
        for event in events:
            start = event.date - timedelta(days=_LOOKBACK_DAYS)
            end = event.date + timedelta(days=_LOOKAHEAD_DAYS)
            try:
                volume = fetch_daily_volume(event.country, start, end, topic=event.topic)
            except NarrativeUnavailableError:
                # Uncached or unavailable: skipped rather than counted as a
                # null result, exactly as the gate itself does.
                continue
            days, physical = daily_physical_intensity(session, event.country, start, end)
            _, narrative = daily_series(volume, start, end)
            windows.append((days, physical, narrative))

        for tau in thresholds:
            observed: list[int] = []
            null: list[int] = []
            for days, physical, narrative in windows:
                result = detect_lead(
                    compute_divergence_series(days, physical, narrative),
                    tau_physical=tau,
                    tau_narrative=tau,
                )
                if result.lead_days is not None:
                    observed.append(result.lead_days)
                null.extend(
                    null_lead_distribution(
                        days,
                        physical,
                        narrative,
                        trials=trials,
                        tau_physical=tau,
                        tau_narrative=tau,
                    )
                )
            if not observed or not null:
                results.append(ThresholdResult(tau, len(observed), None, None, 0.0, 0.0, 1.0))
                continue
            observed_median = statistics.median(observed)
            results.append(
                ThresholdResult(
                    tau=tau,
                    measured=len(observed),
                    observed_median=observed_median,
                    null_median=statistics.median(null),
                    observed_lead_share=sum(1 for v in observed if v >= 1) / len(observed),
                    null_lead_share=sum(1 for v in null if v >= 1) / len(null),
                    p_value=sum(1 for v in null if v >= observed_median) / len(null),
                )
            )
    return results


def render(results: list[ThresholdResult]) -> str:
    lines = [
        "# Lead-Time Gate — Threshold Sensitivity",
        "",
        "The gate's spike thresholds are a pre-registered choice, not a discovered",
        "one. A conclusion that holds only at the chosen value is a property of that",
        "value, so the gate is re-run across a range to see whether it survives.",
        "",
        "| tau | measured | observed median | null median | observed >=1d | null >=1d | p |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r.observed_median is None:
            lines.append(f"| {r.tau:.2f} | {r.measured} | — | — | — | — | — |")
            continue
        lines.append(
            f"| {r.tau:.2f} | {r.measured} | {r.observed_median:+.1f} | "
            f"{r.null_median:+.1f} | {r.observed_lead_share:.0%} | "
            f"{r.null_lead_share:.0%} | {r.p_value:.3f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Threshold sensitivity for the lead-time gate")
    parser.add_argument("--registry", default="app/backtest/events.yaml")
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--out", default="docs/backtest/threshold-sensitivity.md")
    args = parser.parse_args()

    results = sweep(args.registry, trials=args.trials)
    rendered = render(results)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered)
    print(rendered)
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
