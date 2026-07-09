"""Tests for `app.corroboration.rules` — mechanical claim detection + sensor matching."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.corroboration.rules import (
    LOOKAHEAD_HOURS,
    LOOKBACK_HOURS,
    detect_claims,
    evaluate_claim,
    sensor_country,
)

T0 = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
WINDOW = (T0 - timedelta(hours=LOOKBACK_HOURS), T0 + timedelta(hours=LOOKAHEAD_HOURS))


def _sensor(event_id: int, source: str, country: str | None = None, **kwargs) -> dict:
    return {
        "event_id": event_id,
        "source": source,
        "occurred_at": kwargs.pop("occurred_at", T0),
        "country": country,
        "severity": kwargs.pop("severity", 0.3),
        "payload": kwargs.pop("payload", {}),
    }


# --- claim detection -------------------------------------------------------


def test_detect_claims_earthquake() -> None:
    assert detect_claims(["Powerful earthquake strikes Tokyo"]) == {"earthquake"}
    assert detect_claims(["Aftershocks rattle survivors in Turkey"]) == {"earthquake"}


def test_detect_claims_wildfire_and_disaster() -> None:
    assert detect_claims(["Wildfire forces mass evacuation"]) == {"wildfire"}
    assert detect_claims(["Typhoon slams coastal cities, floods follow"]) == {"disaster"}


def test_detect_claims_market_crash() -> None:
    assert detect_claims(["Global stock market crash wipes billions"]) == {"market_crash"}


def test_detect_claims_word_boundaries() -> None:
    """'eruption' must not fire on 'disruption'; 'quake' not on 'quaker'."""
    assert detect_claims(["Rail disruption angers commuters"]) == set()
    assert detect_claims(["Quaker community celebrates anniversary"]) == set()


def test_detect_claims_none_and_multi() -> None:
    assert detect_claims(["Central bank raises interest rates"]) == set()
    assert detect_claims(["Earthquake triggers tsunami warning across the Pacific"]) == {
        "earthquake",
        "disaster",
    }


def test_detect_claims_aggregates_over_member_titles() -> None:
    got = detect_claims(["Wildfire spreads north", "Smoke blankets the capital"])
    assert got == {"wildfire"}


# --- sensor country resolution ---------------------------------------------


def test_sensor_country_prefers_column() -> None:
    assert sensor_country(_sensor(1, "gdacs", country="PH")) == "PH"


def test_sensor_country_usgs_place_tail_fallback() -> None:
    ev = _sensor(1, "usgs-quake", payload={"place": "50 km SW of Shirahama, Japan"})
    assert sensor_country(ev) == "JP"


def test_sensor_country_gdacs_iso3_fallback() -> None:
    ev = _sensor(1, "gdacs", payload={"iso3": "PHL"})
    assert sensor_country(ev) == "PH"


def test_sensor_country_unresolvable() -> None:
    assert sensor_country(_sensor(1, "usgs-quake", payload={})) is None


# --- rule evaluation --------------------------------------------------------


def test_evaluate_confirmed_on_country_and_window_match() -> None:
    check = evaluate_claim(
        "earthquake",
        story_countries={"JP"},
        window=WINDOW,
        sensors=[_sensor(9, "usgs-quake", payload={"place": "12 km N of Sendai, Japan"})],
    )
    assert check["verdict"] == "confirmed"
    assert check["matched_event_id"] == 9
    assert check["evidence"]["country"] == "JP"


def test_evaluate_unconfirmed_wrong_country() -> None:
    check = evaluate_claim(
        "earthquake",
        story_countries={"CL"},
        window=WINDOW,
        sensors=[_sensor(9, "usgs-quake", country="JP")],
    )
    assert check["verdict"] == "unconfirmed"
    assert check["matched_event_id"] is None


def test_evaluate_unconfirmed_outside_window() -> None:
    old = _sensor(9, "usgs-quake", country="JP", occurred_at=WINDOW[0] - timedelta(hours=1))
    check = evaluate_claim("earthquake", story_countries={"JP"}, window=WINDOW, sensors=[old])
    assert check["verdict"] == "unconfirmed"


def test_evaluate_unconfirmed_story_without_geography() -> None:
    check = evaluate_claim(
        "earthquake",
        story_countries=set(),
        window=WINDOW,
        sensors=[_sensor(9, "usgs-quake", country="JP")],
    )
    assert check["verdict"] == "unconfirmed"
    assert check["evidence"]["reason"] == "story-not-geolocated"


def test_evaluate_market_crash_needs_drawdown_threshold() -> None:
    calm = _sensor(5, "yfinance", country="US", severity=0.2)
    stressed = _sensor(6, "yfinance", country="US", severity=0.7)
    below = evaluate_claim("market_crash", story_countries={"US"}, window=WINDOW, sensors=[calm])
    above = evaluate_claim(
        "market_crash", story_countries={"US"}, window=WINDOW, sensors=[calm, stressed]
    )
    assert below["verdict"] == "unconfirmed"
    assert above["verdict"] == "confirmed"
    assert above["matched_event_id"] == 6
