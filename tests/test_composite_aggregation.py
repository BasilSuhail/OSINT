"""Tests for `app.composite.aggregation`."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.composite.aggregation import (
    WILDFIRE_DOMAIN,
    WILDFIRE_SOURCE,
    aggregate_events_to_domain_signals,
    conflict_signal,
    month_start_utc,
    wildfire_signal,
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

    def test_takes_the_strongest_event_per_country_month_domain(self) -> None:
        # Was the mean until #574. A country having a catastrophe during a busy
        # month scored LOWER than a quiet country with one moderate event —
        # measured 11x dilution on live US hazard data (mean 0.095, max 1.000).
        # #528 already established this on the backtest side.
        # Two severity domains, market and hazard. Geopolitical left this test
        # when #680 made it a count rather than a severity — `max` never applied
        # to it again, so asserting it here measured nothing about `max`.
        result = aggregate_events_to_domain_signals(
            [
                _event(country="US", category="market", severity=0.2),
                _event(country="US", category="market", severity=0.6),
                _event(country="US", category="hazard", severity=0.5),
                _event(country="GB", category="market", severity=0.9),
            ]
        )
        us = result[("US", datetime(2026, 6, 1, tzinfo=UTC))]
        gb = result[("GB", datetime(2026, 6, 1, tzinfo=UTC))]
        assert us["market"] == pytest.approx(0.6)
        assert us["hazard"] == pytest.approx(0.5)
        assert gb["market"] == pytest.approx(0.9)

    def test_a_swarm_of_small_events_cannot_outrank_one_severe_one(self) -> None:
        # The reason the FIRMS fix is safe: 536,097 fire pixels, most of them
        # nominal, would otherwise swamp ~1,000 USGS/GDACS rows about 500:1 and
        # pin the hazard domain flat at the mean fire confidence.
        swarm = [_event(country="US", category="hazard", severity=0.5) for _ in range(500)]
        severe = [_event(country="US", category="hazard", severity=0.95)]
        result = aggregate_events_to_domain_signals(swarm + severe)
        assert result[("US", datetime(2026, 6, 1, tzinfo=UTC))]["hazard"] == pytest.approx(0.95)

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


def _firms(
    *,
    country: str | None = "US",
    frp: str | float | None = 10.0,
    occurred_at: datetime | None = None,
    severity: float | None = 0.3,
) -> dict:
    """A stored FIRMS row as the composite worker selects it."""
    return {
        "country": country,
        "category": "hazard",
        "severity": severity,
        "occurred_at": occurred_at or datetime(2026, 6, 18, tzinfo=UTC),
        "source": WILDFIRE_SOURCE,
        "frp": frp,
    }


class TestWildfireDomain:
    """FIRMS gets its own domain, summed on FRP (#579).

    Two quantities that were sharing one bucket: a VIIRS pixel is a heat
    signature, a USGS row is a measured earthquake with casualties attached.
    Under `max` in the hazard domain the fire pixel simply won — 55% of
    country-months pinned at exactly 0.90 (#580).
    """

    def test_firms_lands_in_wildfire_not_hazard(self) -> None:
        result = aggregate_events_to_domain_signals([_firms()])
        bucket = result[("US", datetime(2026, 6, 1, tzinfo=UTC))]
        assert WILDFIRE_DOMAIN in bucket
        assert "hazard" not in bucket

    def test_firms_never_displaces_a_real_hazard(self) -> None:
        # The bug this fixes: a fire pixel outranking a fatal earthquake.
        result = aggregate_events_to_domain_signals(
            [
                _firms(frp=1488.19, severity=0.55),
                _event(category="hazard", severity=0.42),
            ]
        )
        bucket = result[("US", datetime(2026, 6, 1, tzinfo=UTC))]
        assert bucket["hazard"] == 0.42
        assert bucket[WILDFIRE_DOMAIN] == pytest.approx(wildfire_signal(1488.19))

    def test_pixels_sum_rather_than_max(self) -> None:
        # `max` over half a million pixels is the hottest single pixel, which
        # saturates. Total FRP is what actually varies month to month.
        result = aggregate_events_to_domain_signals([_firms(frp=10.0) for _ in range(4)])
        bucket = result[("US", datetime(2026, 6, 1, tzinfo=UTC))]
        assert bucket[WILDFIRE_DOMAIN] == pytest.approx(wildfire_signal(40.0))

    def test_a_busier_fire_month_scores_higher(self) -> None:
        quiet = aggregate_events_to_domain_signals([_firms(frp=50.0)])
        busy = aggregate_events_to_domain_signals([_firms(frp=50.0) for _ in range(20)])
        key = ("US", datetime(2026, 6, 1, tzinfo=UTC))
        assert busy[key][WILDFIRE_DOMAIN] > quiet[key][WILDFIRE_DOMAIN]

    def test_months_stay_separate(self) -> None:
        result = aggregate_events_to_domain_signals(
            [
                _firms(frp=10.0, occurred_at=datetime(2026, 6, 18, tzinfo=UTC)),
                _firms(frp=90.0, occurred_at=datetime(2026, 7, 2, tzinfo=UTC)),
            ]
        )
        assert result[("US", datetime(2026, 6, 1, tzinfo=UTC))][WILDFIRE_DOMAIN] == pytest.approx(
            wildfire_signal(10.0)
        )
        assert result[("US", datetime(2026, 7, 1, tzinfo=UTC))][WILDFIRE_DOMAIN] == pytest.approx(
            wildfire_signal(90.0)
        )

    def test_unreadable_frp_is_skipped_not_counted_as_zero(self) -> None:
        result = aggregate_events_to_domain_signals(
            [_firms(frp=None), _firms(frp="not-a-number"), _firms(frp=-1.0)]
        )
        assert result == {}

    def test_firms_severity_is_never_read_as_a_hazard_signal(self) -> None:
        # Even a FIRMS row carrying a high stored severity must not appear in
        # the hazard domain — that is the overlap #579 removes.
        result = aggregate_events_to_domain_signals([_firms(severity=0.99, frp=1.0)])
        bucket = result[("US", datetime(2026, 6, 1, tzinfo=UTC))]
        assert "hazard" not in bucket
        assert bucket[WILDFIRE_DOMAIN] == pytest.approx(wildfire_signal(1.0))


class TestGeopoliticalDomain:
    """Conflict is counted, not graded (#680).

    Every stored GDELT row has severity >= 0.700, because the parser keeps only
    escalatory CAMEO codes (14-20) and `severity = (10 - goldstein) / 20`. Read
    off a stream where every row is already severe, severity said the same thing
    everywhere: mean 0.9863, sd 0.0523 across 168 countries, which z-scores to
    nothing. Aggregation was not the culprit — the cell mean measured sd 0.0511,
    no better than the max. The information is in how many, not how bad:
    log-scaled counts measured sd 0.797, fifteen times the spread.
    """

    def test_the_signal_is_the_event_count_not_the_severity(self) -> None:
        result = aggregate_events_to_domain_signals(
            [
                _event(category="geopolitical", severity=0.75),
                _event(category="geopolitical", severity=1.0),
                _event(category="geopolitical", severity=0.9),
            ]
        )

        us = result[("US", datetime(2026, 6, 1, tzinfo=UTC))]
        assert us["geopolitical"] == pytest.approx(conflict_signal(3))

    def test_more_conflict_scores_higher(self) -> None:
        result = aggregate_events_to_domain_signals(
            [_event(country="RU", category="geopolitical") for _ in range(50)]
            + [_event(country="NO", category="geopolitical")]
        )

        ru = result[("RU", datetime(2026, 6, 1, tzinfo=UTC))]
        no = result[("NO", datetime(2026, 6, 1, tzinfo=UTC))]
        assert ru["geopolitical"] > no["geopolitical"]

    def test_severity_no_longer_changes_the_signal(self) -> None:
        # The regression that matters: a stream of maximally severe events and a
        # stream of mildly severe ones must now score identically, because the
        # filter upstream already guaranteed every row is severe.
        worst = aggregate_events_to_domain_signals(
            [_event(category="geopolitical", severity=1.0) for _ in range(4)]
        )
        milder = aggregate_events_to_domain_signals(
            [_event(category="geopolitical", severity=0.7) for _ in range(4)]
        )

        key = ("US", datetime(2026, 6, 1, tzinfo=UTC))
        assert worst[key]["geopolitical"] == pytest.approx(milder[key]["geopolitical"])

    def test_a_conflict_row_without_severity_still_counts(self) -> None:
        # Counting does not need a severity, so a row missing one is no longer a
        # reason to discard evidence that something happened.
        result = aggregate_events_to_domain_signals(
            [
                _event(category="geopolitical", severity=None),
                _event(category="geopolitical", severity=0.8),
            ]
        )

        us = result[("US", datetime(2026, 6, 1, tzinfo=UTC))]
        assert us["geopolitical"] == pytest.approx(conflict_signal(2))

    def test_counts_are_per_country_and_per_month(self) -> None:
        june = datetime(2026, 6, 18, tzinfo=UTC)
        july = datetime(2026, 7, 2, tzinfo=UTC)
        result = aggregate_events_to_domain_signals(
            [
                _event(country="US", category="geopolitical", occurred_at=june),
                _event(country="US", category="geopolitical", occurred_at=june),
                _event(country="US", category="geopolitical", occurred_at=july),
                _event(country="GB", category="geopolitical", occurred_at=june),
            ]
        )

        assert result[("US", datetime(2026, 6, 1, tzinfo=UTC))]["geopolitical"] == pytest.approx(
            conflict_signal(2)
        )
        assert result[("US", datetime(2026, 7, 1, tzinfo=UTC))]["geopolitical"] == pytest.approx(
            conflict_signal(1)
        )
        assert result[("GB", datetime(2026, 6, 1, tzinfo=UTC))]["geopolitical"] == pytest.approx(
            conflict_signal(1)
        )

    def test_a_country_with_no_conflict_gets_no_geopolitical_key(self) -> None:
        # Absent, not zero. #683 renormalises weights over present domains, so
        # emitting 0.0 here would reintroduce the imputation it removed.
        result = aggregate_events_to_domain_signals([_event(category="market", severity=0.4)])

        assert "geopolitical" not in result[("US", datetime(2026, 6, 1, tzinfo=UTC))]


class TestConflictSignal:
    def test_zero_events_is_zero(self) -> None:
        assert conflict_signal(0) == 0.0

    def test_monotonic_in_the_count(self) -> None:
        assert conflict_signal(1) < conflict_signal(10) < conflict_signal(1000)

    def test_log_scaled_so_a_loud_country_cannot_dwarf_the_scale(self) -> None:
        # US 34,809 conflict events against Norway's handful is media attention,
        # not conflict. Log keeps the range usable; within-country z-scoring is
        # what actually removes the level (README section 5.3).
        assert conflict_signal(34809) < 5.0
        assert conflict_signal(34809) / conflict_signal(1) < 20.0

    def test_negative_counts_are_treated_as_zero(self) -> None:
        assert conflict_signal(-5) == 0.0


class TestWildfireSignal:
    def test_zero_total_is_zero(self) -> None:
        assert wildfire_signal(0.0) == 0.0

    def test_monotonic(self) -> None:
        assert wildfire_signal(1.0) < wildfire_signal(100.0) < wildfire_signal(10_000.0)

    def test_compresses_orders_of_magnitude(self) -> None:
        # A fire season is not 1000x a quiet month on this scale, it is ~3 more.
        # Not exactly 3: the +1 offset that keeps log(0) defined still shows at
        # the small end.
        assert wildfire_signal(10_000.0) - wildfire_signal(10.0) == pytest.approx(3.0, abs=0.05)
