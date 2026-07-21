"""Aggregation layer — events → per-(country, month, domain) mean severity.

Pure functions only. Composite worker calls these over events fetched from the
events table; tests call them with plain dicts.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

#: The three composite domains. Events with other categories are ignored.
COMPOSITE_CATEGORIES: frozenset[str] = frozenset({"market", "geopolitical", "hazard"})


def month_start_utc(dt: datetime) -> datetime:
    """Truncate a datetime to the first day of its month in UTC."""
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return datetime(dt.year, dt.month, 1, tzinfo=UTC)


def aggregate_events_to_domain_signals(
    events: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, datetime], dict[str, float]]:
    """Group events by (country, month-start) and take the strongest per domain.

    Input items must expose at least: country, category, severity, occurred_at.
    Items with any of those missing or with category outside the composite set
    are silently skipped.

    The month's strongest event, not its mean (#574). Averaging diluted exactly
    the extremes the signal exists to catch: measured on live hazard data, US
    scored mean 0.095 against a max of 1.000, so a country having a catastrophe
    in a busy month read as calmer than a quiet country with one moderate
    event. #528 established the same point on the backtest side, where counting
    rows left 11 of 16 scored events with no measurement at all.

    It is also what makes the FIRMS severity fix safe: 536,097 mostly-nominal
    fire pixels would swamp ~1,000 USGS/GDACS rows roughly 500:1 under a mean
    and pin the hazard domain flat.

    Returns: {(country_iso, month_start): {"market"|"geopolitical"|"hazard": float}}
    Missing domains are simply absent from the inner dict.
    """
    buckets: dict[tuple[str, datetime], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for event in events:
        country = event.get("country")
        category = event.get("category")
        severity = event.get("severity")
        occurred_at = event.get("occurred_at")
        if country is None or category is None or severity is None or occurred_at is None:
            continue
        if category not in COMPOSITE_CATEGORIES:
            continue
        try:
            severity_f = float(severity)
        except (TypeError, ValueError):
            continue
        bucket_start = month_start_utc(occurred_at)
        buckets[(country, bucket_start)][category].append(severity_f)

    return {
        key: {category: max(values) for category, values in inner.items()}
        for key, inner in buckets.items()
    }
