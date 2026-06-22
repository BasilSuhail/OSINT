"""Pure tests for ``app.sources.opensky_fetcher.parse_opensky_body``."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import Category
from app.sources.opensky_fetcher import _state_to_event, parse_opensky_body

FETCHED_AT = datetime(2026, 6, 22, 12, 0, 0, tzinfo=UTC)


def _good_state(icao: str = "a1b2c3", lon: float = -73.9, lat: float = 40.7) -> list:
    return [
        icao,  # 0 icao24
        "AAL100  ",  # 1 callsign
        "United States",  # 2 origin_country
        int(FETCHED_AT.timestamp()),  # 3 time_position
        int(FETCHED_AT.timestamp()),  # 4 last_contact
        lon,  # 5 longitude
        lat,  # 6 latitude
        9144.0,  # 7 baro_altitude
        False,  # 8 on_ground
        249.5,  # 9 velocity
        87.3,  # 10 true_track
        0.0,  # 11 vertical_rate
        None,  # 12
        9450.0,  # 13 geo_altitude
        None,  # 14
        None,  # 15
        None,  # 16
    ]


def test_state_to_event_happy_path() -> None:
    ev = _state_to_event(_good_state(), FETCHED_AT)
    assert ev is not None
    assert ev.source == "opensky-adsb"
    assert ev.category == Category.TRACKING
    assert ev.severity == 0.0
    assert ev.lat == 40.7
    assert ev.lon == -73.9
    assert ev.payload["icao24"] == "a1b2c3"
    assert ev.payload["callsign"] == "AAL100"
    assert ev.payload["origin_country"] == "United States"


def test_state_to_event_returns_none_without_lat_lon() -> None:
    state = _good_state()
    state[5] = None
    state[6] = None
    assert _state_to_event(state, FETCHED_AT) is None


def test_state_to_event_returns_none_for_short_state() -> None:
    assert _state_to_event([], FETCHED_AT) is None
    assert _state_to_event(["only-icao"], FETCHED_AT) is None


def test_state_to_event_returns_none_without_icao24() -> None:
    state = _good_state(icao="")
    assert _state_to_event(state, FETCHED_AT) is None


def test_parse_body_skips_bad_entries() -> None:
    body = {
        "states": [_good_state("aaa111"), _good_state("bbb222", lat=None), _good_state("ccc333")]
    }
    events = parse_opensky_body(body, fetched_at=FETCHED_AT)
    assert len(events) == 2
    assert events[0].payload["icao24"] == "aaa111"
    assert events[1].payload["icao24"] == "ccc333"


def test_parse_body_empty_returns_empty_list() -> None:
    assert parse_opensky_body({"states": []}, fetched_at=FETCHED_AT) == []
    assert parse_opensky_body({}, fetched_at=FETCHED_AT) == []


def test_source_event_id_is_stable_per_icao_and_time() -> None:
    a = _state_to_event(_good_state("xxx111"), FETCHED_AT)
    b = _state_to_event(_good_state("xxx111"), FETCHED_AT)
    assert a is not None
    assert b is not None
    assert a.source_event_id == b.source_event_id
