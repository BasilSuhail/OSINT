"""Tests for `app.sources.fred_fetcher`.

Same approach as the yfinance tests: the HTTP layer is the third-party `fredapi`
library, so unit tests focus on the pure transformation function
`_series_to_events`. Integration tests against the live FRED API are not
included here.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.models import Category
from app.sources.fred_fetcher import FredFetcher, _series_to_events


def _make_series(values: list[float], start: str = "2025-01-01", freq: str = "MS") -> pd.Series:
    index = pd.date_range(start=start, periods=len(values), freq=freq)
    return pd.Series(values, index=index)


class TestSeriesToEvents:
    def test_empty_series_returns_empty_list(self) -> None:
        empty = pd.Series([], dtype=float)
        events = _series_to_events(
            empty,
            series_id="UNRATE",
            country="US",
            units="Percent",
            fetched_at=datetime.now(timezone.utc),
        )
        assert events == []

    def test_simple_series_emits_one_event_per_observation(self) -> None:
        s = _make_series([4.1, 4.2, 4.0])
        events = _series_to_events(
            s,
            series_id="UNRATE",
            country="US",
            units="Percent",
            fetched_at=datetime.now(timezone.utc),
        )
        assert len(events) == 3
        assert all(e.source == "fred" for e in events)
        assert all(e.category == Category.MARKET for e in events)
        assert all(e.country == "US" for e in events)
        assert all(e.severity is None for e in events)
        assert events[0].payload["value"] == pytest.approx(4.1)

    def test_nan_observations_skipped(self) -> None:
        s = _make_series([4.1, float("nan"), 4.0])
        events = _series_to_events(
            s,
            series_id="UNRATE",
            country="US",
            units="Percent",
            fetched_at=datetime.now(timezone.utc),
        )
        assert len(events) == 2
        assert events[0].payload["value"] == pytest.approx(4.1)
        assert events[1].payload["value"] == pytest.approx(4.0)

    def test_source_event_id_includes_series_and_date(self) -> None:
        s = _make_series([2.5])
        events = _series_to_events(
            s,
            series_id="DGS10",
            country="US",
            units="Percent",
            fetched_at=datetime.now(timezone.utc),
        )
        assert events[0].source_event_id == "DGS10:2025-01-01"

    def test_units_propagated_into_payload(self) -> None:
        s = _make_series([305.5])
        events = _series_to_events(
            s,
            series_id="CPIAUCSL",
            country="US",
            units="Index 1982-1984=100",
            fetched_at=datetime.now(timezone.utc),
        )
        assert events[0].payload["units"] == "Index 1982-1984=100"
        assert events[0].payload["series_id"] == "CPIAUCSL"


class TestFredFetcherContract:
    def test_name_and_queue(self) -> None:
        fetcher = FredFetcher()
        assert fetcher.name == "fred"
        assert fetcher.queue == "slow"

    def test_archive_path_partitioned_by_month(self) -> None:
        fetcher = FredFetcher()
        path = fetcher.archive_path()
        assert path.startswith("/mnt/data/parquet/fred/year=")
        assert "month=" in path

    def test_rejects_non_positive_lookback(self) -> None:
        with pytest.raises(ValueError):
            FredFetcher(lookback_days=0)
        with pytest.raises(ValueError):
            FredFetcher(lookback_days=-5)

    def test_fetch_returns_empty_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import settings as settings_module

        monkeypatch.setattr(settings_module.settings, "fred_api_key", "")
        fetcher = FredFetcher()
        assert fetcher.fetch() == []
