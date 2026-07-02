"""Stats layer — tidy weekly rows → per-country coverage-bias statistics.

Pure functions only. `events_per_month` doubles as the country's baseline mean;
`baseline_std` is the population std of monthly volume. Months inside the
coverage window with no rows count as zero-volume months — a reporting dropout
is part of the country's real coverage story, not missing data to be skipped.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from app.labels.rules import month_start_utc


def _months_between(first: datetime, last: datetime) -> int:
    return (last.year - first.year) * 12 + (last.month - first.month) + 1


def compute_coverage(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per-country coverage stats, sorted by total events descending."""
    monthly: dict[str, dict[datetime, int]] = defaultdict(lambda: defaultdict(int))
    fatalities: dict[str, int] = defaultdict(int)
    for row in rows:
        month = month_start_utc(row["week"])
        monthly[row["country"]][month] += int(row["events"])
        fatalities[row["country"]] += int(row["fatalities"])

    global_events = sum(sum(months.values()) for months in monthly.values())

    stats: list[dict[str, Any]] = []
    for country, months in monthly.items():
        first, last = min(months), max(months)
        coverage_months = _months_between(first, last)
        total_events = sum(months.values())
        # Zero-volume months inside the window count toward the baseline.
        volumes = list(months.values()) + [0] * (coverage_months - len(months))
        mean = total_events / coverage_months
        std = (sum((v - mean) ** 2 for v in volumes) / coverage_months) ** 0.5
        stats.append(
            {
                "country": country,
                "coverage_months": coverage_months,
                "observed_months": len(months),
                "total_events": total_events,
                "events_per_month": total_events / coverage_months,
                "global_share": total_events / global_events if global_events else 0.0,
                "fatalities_per_event": (
                    fatalities[country] / total_events if total_events else 0.0
                ),
                "baseline_std": std,
            }
        )
    stats.sort(key=lambda s: (-s["total_events"], s["country"]))
    return stats


def concentration(
    stats: list[dict[str, Any]], *, tops: tuple[int, ...] = (5, 10, 20)
) -> dict[int, float]:
    """Share of global event volume absorbed by the top-N countries."""
    return {n: sum(s["global_share"] for s in stats[:n]) for n in tops}
