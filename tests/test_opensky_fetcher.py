"""Pure tests for ``app.sources.opensky_fetcher.parse_opensky_body``.

Since #496 the fetcher aggregates: one event per country per hour carrying
aircraft counts, rather than one event per aircraft observation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import Category
from app.sources.opensky_fetcher import parse_opensky_body

FETCHED_AT = datetime(2026, 6, 22, 12, 34, 56, tzinfo=UTC)

# Coordinates that resolve unambiguously under the 110 m Natural Earth set.
NEW_YORK = (-73.9, 40.7)
KANSAS = (-98.0, 38.5)
BERLIN = (13.4, 52.5)
MID_ATLANTIC = (-40.0, 0.0)  # open ocean — no country


def _state(
    icao: str = "a1b2c3",
    lonlat: tuple[float, float] = NEW_YORK,
    *,
    on_ground: bool = False,
) -> list:
    lon, lat = lonlat
    return [
        icao,  # 0 icao24
        "AAL100  ",  # 1 callsign
        "United States",  # 2 origin_country
        int(FETCHED_AT.timestamp()),  # 3 time_position
        int(FETCHED_AT.timestamp()),  # 4 last_contact
        lon,  # 5 longitude
        lat,  # 6 latitude
        9144.0,  # 7 baro_altitude
        on_ground,  # 8 on_ground
        249.5,  # 9 velocity
        87.3,  # 10 true_track
        0.0,  # 11 vertical_rate
        None,  # 12
        9450.0,  # 13 geo_altitude
        None,  # 14
        None,  # 15
        None,  # 16
    ]


def _by_country(events: list) -> dict[str, object]:
    return {ev.country: ev for ev in events}


def test_aggregates_one_event_per_country() -> None:
    body = {
        "states": [
            _state("aaa111", NEW_YORK),
            _state("bbb222", KANSAS),
            _state("ccc333", BERLIN),
        ]
    }
    events = parse_opensky_body(body, fetched_at=FETCHED_AT)
    by_country = _by_country(events)
    assert set(by_country) == {"US", "DE"}
    assert by_country["US"].payload["aircraft_count"] == 2
    assert by_country["DE"].payload["aircraft_count"] == 1


def test_event_shape_is_country_scoped_hourly_density() -> None:
    events = parse_opensky_body({"states": [_state()]}, fetched_at=FETCHED_AT)
    assert len(events) == 1
    ev = events[0]
    assert ev.source == "opensky-adsb"
    assert ev.category == Category.TRACKING
    assert ev.severity == 0.0
    assert ev.country == "US"
    # A country aggregate has no single position.
    assert ev.lat is None
    assert ev.lon is None
    # occurred_at is floored to the hour, not the fetch instant.
    assert ev.occurred_at == datetime(2026, 6, 22, 12, 0, 0, tzinfo=UTC)
    assert ev.source_event_id == "US|2026-06-22T12"


def test_counts_split_airborne_and_on_ground() -> None:
    body = {
        "states": [
            _state("aaa111", NEW_YORK, on_ground=False),
            _state("bbb222", KANSAS, on_ground=True),
            _state("ccc333", KANSAS, on_ground=True),
        ]
    }
    ev = _by_country(parse_opensky_body(body, fetched_at=FETCHED_AT))["US"]
    assert ev.payload["aircraft_count"] == 3
    assert ev.payload["airborne_count"] == 1
    assert ev.payload["on_ground_count"] == 2


def test_same_aircraft_counted_once_per_country() -> None:
    # OpenSky can repeat an icao24 within one response; distinct airframes only.
    body = {"states": [_state("dupe01", NEW_YORK), _state("dupe01", KANSAS)]}
    ev = _by_country(parse_opensky_body(body, fetched_at=FETCHED_AT))["US"]
    assert ev.payload["aircraft_count"] == 1


def test_drops_aircraft_that_resolve_to_no_country() -> None:
    body = {"states": [_state("aaa111", MID_ATLANTIC), _state("bbb222", NEW_YORK)]}
    events = parse_opensky_body(body, fetched_at=FETCHED_AT)
    assert set(_by_country(events)) == {"US"}


def test_skips_unusable_states() -> None:
    no_position = _state("bad001")
    no_position[5] = None
    no_position[6] = None
    no_icao = _state("")
    body = {"states": [no_position, no_icao, [], ["only-icao"], _state("good01", NEW_YORK)]}
    events = parse_opensky_body(body, fetched_at=FETCHED_AT)
    assert len(events) == 1
    assert events[0].payload["aircraft_count"] == 1


def test_empty_body_returns_empty_list() -> None:
    assert parse_opensky_body({"states": []}, fetched_at=FETCHED_AT) == []
    assert parse_opensky_body({}, fetched_at=FETCHED_AT) == []


def test_source_event_id_is_stable_within_the_hour() -> None:
    later = datetime(2026, 6, 22, 12, 59, 0, tzinfo=UTC)
    first = parse_opensky_body({"states": [_state()]}, fetched_at=FETCHED_AT)
    second = parse_opensky_body({"states": [_state()]}, fetched_at=later)
    # Same key across polls in one hour: the upsert refreshes rather than
    # appending, so an hour of polling costs one row per country.
    assert first[0].source_event_id == second[0].source_event_id
    assert first[0].occurred_at == second[0].occurred_at


def test_source_event_id_changes_across_hours() -> None:
    next_hour = datetime(2026, 6, 22, 13, 5, 0, tzinfo=UTC)
    first = parse_opensky_body({"states": [_state()]}, fetched_at=FETCHED_AT)
    second = parse_opensky_body({"states": [_state()]}, fetched_at=next_hour)
    assert first[0].source_event_id != second[0].source_event_id


def test_payload_records_the_sample_instant() -> None:
    ev = parse_opensky_body({"states": [_state()]}, fetched_at=FETCHED_AT)[0]
    assert ev.payload["sampled_at"] == FETCHED_AT.isoformat()
