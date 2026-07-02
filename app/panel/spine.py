"""Spine layer — tidy ACLED rows → per-country coverage windows → month grid.

Coverage windows keep the negative class honest: a month before a country's
first observed ACLED week is unknown, not a negative, so it never enters the
panel. Pure functions only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from app.labels.rules import month_start_utc


def coverage_windows(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[datetime, datetime]]:
    """Per-country (first, last) observed month from tidy weekly rows."""
    windows: dict[str, tuple[datetime, datetime]] = {}
    for row in rows:
        country = row["country"]
        month = month_start_utc(row["week"])
        if country in windows:
            first, last = windows[country]
            windows[country] = (min(first, month), max(last, month))
        else:
            windows[country] = (month, month)
    return windows


def build_spine(
    windows: Mapping[str, tuple[datetime, datetime]],
) -> list[dict[str, Any]]:
    """Expand windows into sorted (country, month) grid rows, inclusive."""
    spine: list[dict[str, Any]] = []
    for country in sorted(windows):
        first, last = windows[country]
        month = first
        while month <= last:
            spine.append({"country": country, "month": month})
            month = _next_month(month)
    return spine


def _next_month(month: datetime) -> datetime:
    if month.month == 12:
        return month.replace(year=month.year + 1, month=1)
    return month.replace(month=month.month + 1)
