"""Module A — Macro signals via FRED.

Pulls macroeconomic time series from the Federal Reserve Economic Data API.
Severity is intentionally left as `None` on emitted events: macro indicators
require domain-specific normalisation (z-score within country, rolling-window
thresholds) which is the composite worker's job, not the fetcher's.

FRED coverage is US-centric; non-US macro will arrive via a complementary
source (ECB SDW, OECD MEI) tracked in a separate issue.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
from fredapi import Fred

from app.models import Category, Event
from app.settings import settings
from app.sources.base import Fetcher

#: Per-country FRED series tuples: (series_id, units description). The series
#: identifiers are stable and documented on https://fred.stlouisfed.org/.
SERIES_BY_COUNTRY: dict[str, list[tuple[str, str]]] = {
    "US": [
        ("CPIAUCSL", "Index 1982-1984=100"),  # CPI All Urban Consumers
        ("UNRATE", "Percent"),                # Civilian unemployment rate
        ("DGS10", "Percent"),                 # 10-year Treasury constant maturity yield
    ],
}


def _series_to_events(
    data: pd.Series,
    *,
    series_id: str,
    country: str,
    units: str,
    fetched_at: datetime,
) -> list[Event]:
    """Pure transformation from a FRED pandas Series to canonical events."""
    events: list[Event] = []
    for raw_date, value in data.dropna().items():
        if isinstance(raw_date, pd.Timestamp):
            occurred_at = raw_date.to_pydatetime()
        else:
            occurred_at = pd.Timestamp(raw_date).to_pydatetime()
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)

        events.append(
            Event(
                source="fred",
                source_event_id=f"{series_id}:{occurred_at.date().isoformat()}",
                occurred_at=occurred_at,
                fetched_at=fetched_at,
                category=Category.MARKET,
                severity=None,  # normalised by the composite worker, not here
                country=country,
                keywords=[series_id, "macro"],
                payload={
                    "series_id": series_id,
                    "value": float(value),
                    "units": units,
                },
            )
        )
    return events


class FredFetcher(Fetcher):
    """Fetcher implementation for the FRED macro panel."""

    name = "fred"
    queue = "slow"

    def __init__(self, *, lookback_days: int = 365) -> None:
        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        self.lookback_days = lookback_days

    def fetch(self) -> list[Event]:
        if not settings.fred_api_key:
            return []

        fred = Fred(api_key=settings.fred_api_key)
        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(days=self.lookback_days)).date().isoformat()

        all_events: list[Event] = []
        for country, series_list in SERIES_BY_COUNTRY.items():
            for series_id, units in series_list:
                data = fred.get_series(series_id, observation_start=start_date)
                all_events.extend(
                    _series_to_events(
                        data,
                        series_id=series_id,
                        country=country,
                        units=units,
                        fetched_at=now,
                    )
                )
        return all_events

    def archive_path(self) -> str:
        now = datetime.now(timezone.utc)
        return f"/mnt/data/parquet/fred/year={now.year}/month={now.month:02d}/"
