"""Module A — Market signals via yfinance.

Pulls daily close prices for one country-ETF per country in the panel, computes
drawdown from a rolling maximum, and emits one canonical `Event` per
(country, trading day). Drawdown is the severity proxy: deeper drawdown = more
market stress.

The price/ETF mapping is intentionally country-level (ETFs trade on US
exchanges so yfinance returns them reliably). Per-country sovereign yields and
FX series live in `fred_fetcher.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from app.models import Category, Event
from app.sources.base import Fetcher

#: Country ISO 3166-1 alpha-2 → ETF ticker. ETFs picked because they trade on
#: US exchanges so the data is always available without local-exchange quirks.
COUNTRY_ETFS: dict[str, str] = {
    "US": "SPY",  # SPDR S&P 500
    "GB": "EWU",  # iShares UK
    "DE": "EWG",  # iShares Germany
    "JP": "EWJ",  # iShares Japan
    "BR": "EWZ",  # iShares Brazil
    "IN": "INDA",  # iShares India
    "CN": "FXI",  # iShares China Large-Cap
    "TR": "TUR",  # iShares Turkey
    "MX": "EWW",  # iShares Mexico
    "ZA": "EZA",  # iShares South Africa
}

#: Drawdown (percent) at which severity saturates at 1.0. A 30% drawdown is
#: roughly the "GFC-2008" magnitude and corresponds to "maximum stress" here.
SEVERITY_SATURATION_PCT: float = 30.0

#: Window used for the rolling peak from which drawdown is measured.
ROLLING_WINDOW_DAYS: int = 30


def _compute_events(
    df: pd.DataFrame,
    *,
    country: str,
    ticker: str,
    fetched_at: datetime,
    lookback_days: int,
) -> list[Event]:
    """Pure transformation: price history → canonical events.

    Kept separate from the HTTP layer so it can be unit tested without
    mocking yfinance.
    """
    if df.empty:
        return []

    closes = df["Close"].astype(float)
    rolling_max = closes.rolling(window=ROLLING_WINDOW_DAYS, min_periods=1).max()
    drawdown_pct = ((rolling_max - closes) / rolling_max * 100.0).fillna(0.0)

    recent_index = df.index[-lookback_days:]
    events: list[Event] = []
    for ts in recent_index:
        close_raw = closes.loc[ts]
        dd_raw = drawdown_pct.loc[ts]
        if pd.isna(close_raw) or pd.isna(dd_raw):
            # yfinance returns NaN closes on non-trading days (weekends, holidays)
            # or when a ticker has no data on the requested date. NaN is not valid
            # JSON, so the row cannot reach Postgres JSONB — drop it here.
            continue
        close = float(close_raw)
        dd = float(dd_raw)
        severity = max(0.0, min(dd / SEVERITY_SATURATION_PCT, 1.0))

        occurred_at = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)

        payload: dict[str, Any] = {
            "ticker": ticker,
            "close": close,
            "volume": float(df["Volume"].loc[ts]) if "Volume" in df.columns else 0.0,
            "rolling_max_30d": float(rolling_max.loc[ts]),
            "drawdown_pct": dd,
        }

        events.append(
            Event(
                source=YFinanceFetcher.name,
                source_event_id=f"{ticker}:{occurred_at.isoformat()}",
                occurred_at=occurred_at,
                fetched_at=fetched_at,
                category=Category.MARKET,
                severity=severity,
                country=country,
                keywords=[ticker, "etf", "drawdown"],
                payload=payload,
            )
        )

    return events


class YFinanceFetcher(Fetcher):
    """Fetcher implementation for the yfinance country-ETF panel."""

    name = "yfinance"
    queue = "fast"

    def __init__(self, lookback_days: int = 5) -> None:
        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        self.lookback_days = lookback_days

    def fetch(self) -> list[Event]:
        now = datetime.now(UTC)
        # Pull extra history so the rolling-max window is warm.
        start = now - timedelta(days=self.lookback_days + ROLLING_WINDOW_DAYS * 2)

        all_events: list[Event] = []
        for country, ticker in COUNTRY_ETFS.items():
            history = yf.Ticker(ticker).history(start=start, end=now, interval="1d")
            all_events.extend(
                _compute_events(
                    history,
                    country=country,
                    ticker=ticker,
                    fetched_at=now,
                    lookback_days=self.lookback_days,
                )
            )
        return all_events

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return (
            f"/mnt/data/parquet/yfinance/year={now.year}/month={now.month:02d}/day={now.day:02d}/"
        )
