"""Tests for `app.sources.fred_fetcher`.

Same approach as the yfinance tests: the HTTP layer is the third-party `fredapi`
library, so unit tests focus on the pure transformation function
`_series_to_events`. Integration tests against the live FRED API are not
included here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from app.composite.normalization import MIN_HISTORY
from app.models import Category
from app.sources.fred_fetcher import FredFetcher, _series_to_events

NOW = datetime(2026, 7, 29, tzinfo=UTC)


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
            fetched_at=datetime.now(UTC),
        )
        assert events == []

    def test_simple_series_emits_one_event_per_observation(self) -> None:
        s = _make_series([4.1, 4.2, 4.0])
        events = _series_to_events(
            s,
            series_id="UNRATE",
            country="US",
            units="Percent",
            fetched_at=datetime.now(UTC),
        )
        assert len(events) == 3
        assert all(e.source == "fred" for e in events)
        assert all(e.category == Category.MARKET for e in events)
        assert all(e.country == "US" for e in events)
        assert all(e.severity is None for e in events)
        assert events[0].payload["value"] == pytest.approx(4.1)

    def test_cold_start_observations_carry_no_severity(self) -> None:
        # No basis for calling a value unusual means no severity. None, not 0.0
        # — the composite filters null severity out, which is the honest
        # outcome, whereas 0.0 asserts "perfectly normal" about a value nothing
        # has judged (#683's mistake).
        #
        # The boundary is MIN_HISTORY + 1 observations, not MIN_HISTORY: the
        # first observation yields no difference, so scoring changes costs one
        # more point before anything can be judged.
        cold = MIN_HISTORY + 1
        s = _make_series([4.1, 4.2, 4.0, 4.1, 4.15, 4.2])
        events = _series_to_events(
            s, series_id="UNRATE", country="US", units="Percent", fetched_at=NOW
        )

        assert [e.severity for e in events[:cold]] == [None] * cold
        assert events[cold].severity is not None

    def test_a_value_in_line_with_its_history_scores_low(self) -> None:
        s = _make_series([4.0, 4.1, 3.9, 4.0, 4.05])
        events = _series_to_events(
            s, series_id="UNRATE", country="US", units="Percent", fetched_at=NOW
        )

        assert events[-1].severity is not None
        assert events[-1].severity < 0.5

    def test_a_spike_against_a_quiet_history_scores_high(self) -> None:
        # Unemployment steady near 4%, then 9%: the whole point of the domain.
        s = _make_series([4.0, 4.1, 3.9, 4.0, 9.0])
        events = _series_to_events(
            s, series_id="UNRATE", country="US", units="Percent", fetched_at=NOW
        )

        assert events[-1].severity == pytest.approx(1.0)

    def test_a_collapse_scores_as_high_as_a_spike(self) -> None:
        # |z|, not z: the claim is "unusual against its own past", and a rate
        # halving is as much a macro event as a rate doubling. Direction is a
        # separate question this deliberately does not answer.
        up = _make_series([4.0, 4.1, 3.9, 4.0, 8.0])
        down = _make_series([8.0, 8.1, 7.9, 8.0, 4.0])

        up_events = _series_to_events(
            up, series_id="UNRATE", country="US", units="Percent", fetched_at=NOW
        )
        down_events = _series_to_events(
            down, series_id="UNRATE", country="US", units="Percent", fetched_at=NOW
        )

        assert up_events[-1].severity == pytest.approx(down_events[-1].severity)

    def test_severity_never_leaves_the_unit_interval(self) -> None:
        # An absurd outlier must saturate rather than escape [0, 1] — the
        # composite's contract is a severity in that range.
        s = _make_series([4.0, 4.1, 3.9, 4.0, 1e6])
        events = _series_to_events(
            s, series_id="UNRATE", country="US", units="Percent", fetched_at=NOW
        )

        assert all(e.severity is None or 0.0 <= e.severity <= 1.0 for e in events)
        assert events[-1].severity == pytest.approx(1.0)

    def test_a_flat_history_yields_zero_rather_than_a_division_by_zero(self) -> None:
        s = _make_series([4.0, 4.0, 4.0, 4.0, 4.0, 4.0])
        events = _series_to_events(
            s, series_id="UNRATE", country="US", units="Percent", fetched_at=NOW
        )

        assert events[-1].severity == pytest.approx(0.0)

    def test_raw_value_is_still_preserved_in_the_payload(self) -> None:
        # Severity is derived; the observation itself must survive unchanged so
        # the derivation stays auditable.
        s = _make_series([4.0, 4.1, 3.9, 4.0, 9.0])
        events = _series_to_events(
            s, series_id="UNRATE", country="US", units="Percent", fetched_at=NOW
        )

        assert events[-1].payload["value"] == pytest.approx(9.0)

    def test_severity_is_computed_in_date_order_not_arrival_order(self) -> None:
        # The z-score is causal — position i sees only what precedes it — so a
        # shuffled series would silently score against the wrong history.
        ordered = _make_series([4.0, 4.1, 3.9, 4.0, 9.0])
        shuffled = ordered.iloc[[4, 0, 2, 1, 3]]

        from_ordered = _series_to_events(
            ordered, series_id="UNRATE", country="US", units="Percent", fetched_at=NOW
        )
        from_shuffled = _series_to_events(
            shuffled, series_id="UNRATE", country="US", units="Percent", fetched_at=NOW
        )

        assert [e.severity for e in from_ordered] == [e.severity for e in from_shuffled]

    def test_nan_observations_skipped(self) -> None:
        s = _make_series([4.1, float("nan"), 4.0])
        events = _series_to_events(
            s,
            series_id="UNRATE",
            country="US",
            units="Percent",
            fetched_at=datetime.now(UTC),
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
            fetched_at=datetime.now(UTC),
        )
        assert events[0].source_event_id == "DGS10:2025-01-01"

    def test_units_propagated_into_payload(self) -> None:
        s = _make_series([305.5])
        events = _series_to_events(
            s,
            series_id="CPIAUCSL",
            country="US",
            units="Index 1982-1984=100",
            fetched_at=datetime.now(UTC),
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
