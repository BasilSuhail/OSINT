"""Orbital prediction is checkable against what the archive actually recorded,
so it is checked rather than believed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.enrichment import satellite_pass as sp

#: Real published elements, epoch 2026-08-09. Held here so the test never
#: reaches the network and never changes answer because somebody else's server
#: refreshed a file.
ELEMENTS = """SENTINEL-2A
1 40697U 15028A   26221.29162428 -.00000152  00000+0 -41436-4 0  9990
2 40697  98.5658 295.3818 0001356  90.7501 269.3838 14.30819839581326
SENTINEL-2B
1 42063U 17013A   26221.28442245 -.00000174  00000+0 -49727-4 0  9997
2 42063  98.5665 295.3020 0001265  93.7984 266.3344 14.30820378492235
SENTINEL-2C
1 60989U 24157A   26221.17953895  .00000033  00000+0  29206-4 0  9999
2 60989  98.5664 295.2041 0001304 107.1093 253.0233 14.30821377100560
NOT-A-SENTINEL
1 25544U 98067A   26221.50000000  .00016717  00000+0  10270-3 0  9007
2 25544  51.6400 208.9163 0006317  69.9862 290.1712 15.49181247 20000
"""

PARIS = (48.8566, 2.3522)


def _client() -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=ELEMENTS)

    return httpx.Client(transport=httpx.MockTransport(handle))


@pytest.fixture(autouse=True)
def _clear():
    sp.clear_cache()
    yield
    sp.clear_cache()


def test_only_the_satellites_the_screen_is_about_are_propagated():
    parsed = sp.parse_elements(ELEMENTS)
    assert [name for name, _ in parsed] == ["SENTINEL-2A", "SENTINEL-2B", "SENTINEL-2C"]


def test_a_truncated_block_is_skipped_not_guessed_at():
    # The propagator validates nothing: handed "1 garbage" it returns an object
    # that happily propagates to nonsense. Length is the guard.
    assert sp.parse_elements("SENTINEL-2A\n1 garbage\n2 garbage\n") == []
    assert sp.parse_elements("SENTINEL-2A\n") == []


@pytest.mark.parametrize(
    ("stated", "platform"),
    [
        ("2026-08-07T10:46:00", "SENTINEL-2C"),
        ("2026-08-05T10:56:00", "SENTINEL-2B"),
        ("2026-08-02T10:57:00", "SENTINEL-2A"),
    ],
)
def test_known_captures_are_predicted_as_overflights(stated, platform):
    """Three captures the archive really recorded over one point.

    Each must come out as an overflight by the right spacecraft, inside the
    swath, close to the moment the product claims — allowing for the product
    timestamp being the datastrip's sensing start rather than the instant over
    this particular point. Measured separately, that gap is 650-690 s.
    """
    when = datetime.fromisoformat(stated).replace(tzinfo=UTC)
    sat = dict(sp.parse_elements(ELEMENTS))[platform]

    closest_km = min(
        sp.ground_distance_km(*PARIS, *point)
        for point in (
            sp._subpoint(sat, when + timedelta(seconds=offset)) for offset in range(0, 1201, 10)
        )
        if point is not None
    )
    assert closest_km < 145.0, f"{platform} never came within the swath of {stated}"


def test_the_sun_is_up_at_local_noon_and_down_at_local_midnight():
    noon = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
    assert sp.sun_elevation_deg(51.5, 0.0, noon) > 50
    midnight = datetime(2026, 6, 21, 0, 0, tzinfo=UTC)
    assert sp.sun_elevation_deg(51.5, 0.0, midnight) < 0


def test_a_pass_is_found_and_is_in_daylight():
    start = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    result = sp.next_overpass(*PARIS, after=start, client=_client())
    assert result is not None
    at = datetime.fromisoformat(result["at"])
    assert start <= at <= start + timedelta(days=6)
    assert result["platform"].startswith("Sentinel-2")
    assert 0 < result["hours_away"] <= 6 * 24
    assert sp.sun_elevation_deg(*PARIS, at) > 5


def test_a_point_the_orbit_never_reaches_gets_no_pass():
    """Sun-synchronous at 98.57 degrees turns back below about 81 degrees.

    Measured: the closest the ground track comes to 89 N in a day is 845 km.
    A screen that invented a pass for somewhere the spacecraft cannot go would
    be worse than one that says nothing.
    """
    start = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    assert sp.next_overpass(89.0, 0.0, after=start, client=_client()) is None


def test_a_high_latitude_point_inside_the_orbit_is_overflown_often():
    start = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    result = sp.next_overpass(70.0, 20.0, after=start, client=_client())
    assert result is not None
    assert result["hours_away"] < 24


def test_coordinates_off_the_globe_have_no_answer():
    assert sp.next_overpass(120.0, 500.0, client=_client()) is None


def test_elements_are_fetched_once_inside_the_window():
    calls = {"n": 0}

    def counting(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text=ELEMENTS)

    client = httpx.Client(transport=httpx.MockTransport(counting))
    start = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    sp.next_overpass(*PARIS, after=start, client=client)
    sp.next_overpass(*PARIS, after=start, client=client)
    assert calls["n"] == 1
