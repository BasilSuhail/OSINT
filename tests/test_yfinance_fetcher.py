"""Tests for `app.sources.yfinance_fetcher`.

The HTTP layer is owned by yfinance, so tests focus on the pure transformation
function `_compute_events`. Integration tests against the live API are
deliberately not included here; they belong in a separate slow suite.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.models import Category
from app.sources.yfinance_fetcher import (
    ROLLING_WINDOW_DAYS,
    SEVERITY_SATURATION_PCT,
    YFinanceFetcher,
    _compute_events,
)


def _make_price_history(prices: list[float]) -> pd.DataFrame:
    dates = pd.date_range(end="2026-06-18", periods=len(prices), freq="B", tz="UTC")
    return pd.DataFrame({"Close": prices, "Volume": [1_000_000] * len(prices)}, index=dates)


class TestComputeEvents:
    def test_empty_history_returns_empty_list(self) -> None:
        empty = pd.DataFrame(columns=["Close", "Volume"])
        events = _compute_events(
            empty,
            country="US",
            ticker="SPY",
            fetched_at=datetime.now(timezone.utc),
            lookback_days=5,
        )
        assert events == []

    def test_steady_prices_produce_zero_severity(self) -> None:
        df = _make_price_history([100.0] * 40)
        events = _compute_events(
            df, country="US", ticker="SPY", fetched_at=datetime.now(timezone.utc), lookback_days=5
        )
        assert len(events) == 5
        assert all(e.severity == 0.0 for e in events)
        assert all(e.category == Category.MARKET for e in events)
        assert all(e.country == "US" for e in events)

    def test_drawdown_maps_to_severity(self) -> None:
        # 40 days at 100, then drop to 70 → drawdown should be 30% → severity 1.0.
        prices = [100.0] * 40 + [70.0]
        df = _make_price_history(prices)
        events = _compute_events(
            df, country="US", ticker="SPY", fetched_at=datetime.now(timezone.utc), lookback_days=1
        )
        assert len(events) == 1
        assert events[0].severity == pytest.approx(1.0, abs=1e-6)
        assert events[0].payload["drawdown_pct"] == pytest.approx(30.0, abs=1e-6)

    def test_partial_drawdown_scales_linearly(self) -> None:
        # Drop of 15% → severity 0.5 with saturation at 30%.
        prices = [100.0] * 40 + [85.0]
        df = _make_price_history(prices)
        events = _compute_events(
            df, country="US", ticker="SPY", fetched_at=datetime.now(timezone.utc), lookback_days=1
        )
        assert events[0].severity == pytest.approx(0.5, abs=1e-6)

    def test_severity_saturates_at_one(self) -> None:
        # Drop of 80% — far beyond the saturation point.
        prices = [100.0] * 40 + [20.0]
        df = _make_price_history(prices)
        events = _compute_events(
            df, country="US", ticker="SPY", fetched_at=datetime.now(timezone.utc), lookback_days=1
        )
        assert events[0].severity == 1.0
        assert events[0].payload["drawdown_pct"] > SEVERITY_SATURATION_PCT

    def test_source_event_id_is_ticker_plus_timestamp(self) -> None:
        prices = [100.0] * 5
        df = _make_price_history(prices)
        events = _compute_events(
            df, country="US", ticker="SPY", fetched_at=datetime.now(timezone.utc), lookback_days=2
        )
        for event in events:
            assert event.source_event_id.startswith("SPY:")
            assert event.source_event_id.endswith(event.occurred_at.isoformat())

    def test_lookback_limits_event_count(self) -> None:
        prices = [100.0 - i for i in range(60)]
        df = _make_price_history(prices)
        events = _compute_events(
            df, country="GB", ticker="EWU", fetched_at=datetime.now(timezone.utc), lookback_days=10
        )
        assert len(events) == 10


class TestYFinanceFetcherContract:
    def test_name_and_queue(self) -> None:
        fetcher = YFinanceFetcher()
        assert fetcher.name == "yfinance"
        assert fetcher.queue == "fast"

    def test_archive_path_partitioned_by_date(self) -> None:
        fetcher = YFinanceFetcher()
        path = fetcher.archive_path()
        assert path.startswith("/mnt/data/parquet/yfinance/year=")
        assert "month=" in path
        assert "day=" in path

    def test_rejects_non_positive_lookback(self) -> None:
        with pytest.raises(ValueError):
            YFinanceFetcher(lookback_days=0)
        with pytest.raises(ValueError):
            YFinanceFetcher(lookback_days=-1)

    def test_rolling_window_constant_is_positive(self) -> None:
        assert ROLLING_WINDOW_DAYS > 0
