"""Module A — Macro signals via FRED.

Pulls macroeconomic time series from the Federal Reserve Economic Data API.

Severity is computed here, from each series' own recent history (#681). It used
to be emitted as `None` behind a comment saying normalisation was "the composite
worker's job" — but the composite filters `severity IS NOT NULL` before it
normalises anything, so all 293 stored rows were silently discarded and the
market domain ran on yfinance alone. The handoff described by that comment had
no receiving end.

FRED coverage is US-centric; non-US macro will arrive via a complementary
source (ECB SDW, OECD MEI) tracked in a separate issue. Fixing severity
therefore deepens the market domain for one country — it does not widen it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
from fredapi import Fred

from app.composite.normalization import MIN_HISTORY, rolling_zscore
from app.models import Category, Event
from app.settings import settings
from app.sources.base import Fetcher

#: Per-country FRED series tuples: (series_id, units description). The series
#: identifiers are stable and documented on https://fred.stlouisfed.org/.
SERIES_BY_COUNTRY: dict[str, list[tuple[str, str]]] = {
    "US": [
        ("CPIAUCSL", "Index 1982-1984=100"),  # CPI All Urban Consumers
        ("UNRATE", "Percent"),  # Civilian unemployment rate
        ("DGS10", "Percent"),  # 10-year Treasury constant maturity yield
    ],
}


#: |z| at or above this counts as maximally unusual. Three population standard
#: deviations against the series' own recent history — chosen before any result
#: was measured, and a judgement rather than a derivation (#681).
SEVERITY_Z_CAP: float = 3.0


def _severity_from_z(z: float) -> float:
    """Map a z-score to the [0, 1] severity every other source emits.

    `abs`, because the claim is "unusual against its own past" — the framing the
    whole composite rests on. A collapsing rate is as much a macro event as a
    spiking one, and which direction is *bad* differs per series: high
    unemployment and high CPI are both bad, a high 10-year yield is neither on
    its own. Answering direction needs a per-series stance this does not take.
    """
    return min(1.0, abs(z) / SEVERITY_Z_CAP)


def _series_to_events(
    data: pd.Series,
    *,
    series_id: str,
    country: str,
    units: str,
    fetched_at: datetime,
) -> list[Event]:
    """Pure transformation from a FRED pandas Series to canonical events.

    Severity is derived here rather than downstream (#681). It used to be left
    None behind a comment saying the composite would normalise it; the composite
    filters null severity out before normalising anything, so all 293 stored
    rows were dropped and the market domain ran on yfinance alone.

    The observation itself carries no severity — 4.1% unemployment is not
    "severe" at any absolute level — so severity is its deviation from this
    series' own preceding values, which is the same question the composite asks
    of every domain one level up.
    """
    clean = data.dropna().sort_index()
    values = [float(v) for v in clean.to_numpy()]

    # Score the change, not the level. Measured against the 293 stored rows,
    # z-scoring levels gave CPIAUCSL a mean severity of 0.744 and a *minimum* of
    # 0.506: CPI is a monotonically rising index, so every month sits above its
    # own trailing mean and the series reads as permanently alarming. That is
    # trend, not anomaly. First differences drop it to mean 0.498 / min 0.024,
    # and DGS10's saturated observations from 17 of 266 to 5 of 265.
    diffs = [values[i] - values[i - 1] for i in range(1, len(values))]
    # Causal by construction: diff position j is scored against the preceding
    # window only, so re-fetching a longer window never rewrites an earlier
    # severity. diffs[j] belongs to observation j + 1.
    zscores = rolling_zscore(diffs)

    events: list[Event] = []
    for i, (raw_date, value) in enumerate(clean.items()):
        if isinstance(raw_date, pd.Timestamp):
            occurred_at = raw_date.to_pydatetime()
        else:
            occurred_at = pd.Timestamp(raw_date).to_pydatetime()
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)

        events.append(
            Event(
                source="fred",
                source_event_id=f"{series_id}:{occurred_at.date().isoformat()}",
                occurred_at=occurred_at,
                fetched_at=fetched_at,
                category=Category.MARKET,
                # None, not 0.0, while history is too short to judge against:
                # the composite drops null severity, which is the honest
                # outcome, whereas 0.0 would assert "perfectly normal" about a
                # value nothing has assessed. That imputation is #683.
                severity=(_severity_from_z(zscores[i - 1]) if i - 1 >= MIN_HISTORY else None),
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
        now = datetime.now(UTC)
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
        now = datetime.now(UTC)
        return f"/mnt/data/parquet/fred/year={now.year}/month={now.month:02d}/"
