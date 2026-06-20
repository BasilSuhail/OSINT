"""Tests for `app.composite.aggregation`."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.composite.aggregation import (
    aggregate_events_to_domain_signals,
    month_start_utc,
)


def _event(
    *,
    country: str | None = "US",
    category: str | None = "market",
    severity: float | None = 0.5,
    occurred_at: datetime | None = None,
) -> dict:
    return {
        "country": country,
        "category": category,
        "severity": severity,
        "occurred_at": occurred_at or datetime(2026, 6, 18, tzinfo=UTC),
    }


class TestMonthStartUtc:
    def test_truncates_to_first_of_month(self) -> None:
        dt = datetime(2026, 6, 18, 14, 30, tzinfo=UTC)
        assert month_start_utc(dt) == datetime(2026, 6, 1, tzinfo=UTC)

    def test_naive_treated_as_utc(self) -> None:
        dt = datetime(2026, 6, 18, 14, 30)
        assert month_start_utc(dt) == datetime(2026, 6, 1, tzinfo=UTC)

    def test_other_timezone_converted_to_utc_then_truncated(self) -> None:
        from datetime import timedelta
        from datetime import timezone as tz

        ny = tz(timedelta(hours=-4))
        dt = datetime(2026, 7, 1, 1, 0, tzinfo=ny)  # 2026-07-01 05:00 UTC
        assert month_start_utc(dt) == datetime(2026, 7, 1, tzinfo=UTC)


class TestAggregate:
    def test_empty_input(self) -> None:
        assert aggregate_events_to_domain_signals([]) == {}

    def test_single_event_emits_one_bucket(self) -> None:
        result = aggregate_events_to_domain_signals(
            [_event(country="US", category="market", severity=0.4)]
        )
        assert result == {("US", datetime(2026, 6, 1, tzinfo=UTC)): {"market": 0.4}}

    def test_means_per_country_month_domain(self) -> None:
        result = aggregate_events_to_domain_signals(
            [
                _event(country="US", category="market", severity=0.2),
                _event(country="US", category="market", severity=0.6),
                _event(country="US", category="geopolitical", severity=0.5),
                _event(country="GB", category="market", severity=0.9),
            ]
        )
        us = result[("US", datetime(2026, 6, 1, tzinfo=UTC))]
        gb = result[("GB", datetime(2026, 6, 1, tzinfo=UTC))]
        assert us["market"] == pytest.approx(0.4)
        assert us["geopolitical"] == pytest.approx(0.5)
        assert gb["market"] == pytest.approx(0.9)

    def test_splits_by_month(self) -> None:
        jun = datetime(2026, 6, 15, tzinfo=UTC)
        jul = datetime(2026, 7, 15, tzinfo=UTC)
        result = aggregate_events_to_domain_signals(
            [
                _event(country="US", category="market", severity=0.2, occurred_at=jun),
                _event(country="US", category="market", severity=0.8, occurred_at=jul),
            ]
        )
        assert result[("US", datetime(2026, 6, 1, tzinfo=UTC))]["market"] == 0.2
        assert result[("US", datetime(2026, 7, 1, tzinfo=UTC))]["market"] == 0.8

    def test_skips_none_fields(self) -> None:
        result = aggregate_events_to_domain_signals(
            [
                _event(country=None),
                _event(category=None),
                _event(severity=None),
                _event(occurred_at=None),
                _event(country="US", category="market", severity=0.4),
            ]
        )
        assert len(result) == 1

    def test_skips_non_composite_categories(self) -> None:
        result = aggregate_events_to_domain_signals(
            [
                _event(category="weather"),
                _event(category="news"),
                _event(category="tracking"),
                _event(country="US", category="hazard", severity=0.5),
            ]
        )
        assert ("US", datetime(2026, 6, 1, tzinfo=UTC)) in result
        assert all(set(v).issubset({"market", "geopolitical", "hazard"}) for v in result.values())

    def test_non_numeric_severity_skipped(self) -> None:
        result = aggregate_events_to_domain_signals(
            [
                _event(severity="not-a-number"),  # type: ignore[arg-type]
                _event(country="US", category="market", severity=0.7),
            ]
        )
        only_bucket = result[("US", datetime(2026, 6, 1, tzinfo=UTC))]
        assert only_bucket["market"] == 0.7
