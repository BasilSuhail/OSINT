"""Presence is drawn and discarded. These tests hold that line."""

from __future__ import annotations

import ast
import pathlib

import httpx
import pytest

from app.presence import aircraft

#: Trimmed from a real response, keeping the shapes that matter: a positioned
#: aircraft with everything, one without a track, one squawking a distress
#: code, and one with no position at all.
MIL = {
    "ac": [
        {
            "hex": "ae6472",
            "type": "adsb_icao",
            "flight": "KING98  ",
            "r": "17-5898",
            "t": "C30J",
            "alt_baro": 1750,
            "gs": 209.3,
            "track": 202.77,
            "squawk": "0466",
            "emergency": "none",
            "lat": 61.058474,
            "lon": -149.802958,
        },
        {
            "hex": "ae1460",
            "flight": "SHADY41 ",
            "r": "10-0002",
            "t": "TWR",
            "alt_baro": "ground",
            "gs": 0.0,
            "squawk": "1200",
            "lat": 32.4,
            "lon": -97.3,
        },
        {
            "hex": "43c7fc",
            "flight": "RRR2201 ",
            "t": "A400",
            "alt_baro": 24000,
            "track": 95.1,
            "squawk": "7700",
            "emergency": "general",
            "lat": 51.2,
            "lon": 1.4,
        },
        {"hex": "ae1234", "flight": "NOPOS01 ", "t": "C17"},
    ]
}

SQK = {
    "ac": [
        {
            "hex": "4ca9d1",
            "flight": "EIN123  ",
            "t": "A320",
            "alt_baro": 31000,
            "track": 270.0,
            "squawk": "7600",
            "lat": 53.1,
            "lon": -6.2,
        }
    ]
}

EMPTY = {"ac": [], "total": 0}


def _handler(*, fail_first: bool = False, fail_all: bool = False):
    def handle(request: httpx.Request) -> httpx.Response:
        if fail_all:
            raise httpx.ConnectError("refused")
        path = request.url.path
        if fail_first and "adsb.lol" in str(request.url.host):
            raise httpx.ConnectError("refused")
        if path.endswith("/v2/mil"):
            return httpx.Response(200, json=MIL)
        if path.endswith("/v2/sqk/7600"):
            return httpx.Response(200, json=SQK)
        return httpx.Response(200, json=EMPTY)

    return handle


def _client(**kwargs) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(_handler(**kwargs)))


@pytest.fixture(autouse=True)
def _clear():
    aircraft.clear_cache()
    yield
    aircraft.clear_cache()


def test_an_aircraft_with_no_position_is_dropped():
    result = aircraft.live_aircraft(client=_client())
    assert "ae1234" not in {a["hex"] for a in result["aircraft"]}


def test_the_aircraft_type_comes_from_t_not_from_the_message_type():
    # `type` is "adsb_icao" on every row; reading it would label every mark
    # identically and tell the reader nothing.
    result = aircraft.live_aircraft(client=_client())
    king = next(a for a in result["aircraft"] if a["hex"] == "ae6472")
    assert king["type"] == "C30J"
    assert king["callsign"] == "KING98"


def test_a_distress_squawk_outranks_being_military():
    result = aircraft.live_aircraft(client=_client())
    kinds = {a["hex"]: a["kind"] for a in result["aircraft"]}
    assert kinds["43c7fc"] == "distress"
    assert kinds["ae6472"] == "military"


def test_distressed_aircraft_are_listed_first():
    result = aircraft.live_aircraft(client=_client())
    assert result["aircraft"][0]["kind"] == "distress"


def test_an_aircraft_on_both_lists_appears_once():
    result = aircraft.live_aircraft(client=_client())
    hexes = [a["hex"] for a in result["aircraft"]]
    assert len(hexes) == len(set(hexes))


def test_a_missing_track_is_absent_rather_than_north():
    # North is a claim. No rotation is not.
    result = aircraft.live_aircraft(client=_client())
    shady = next(a for a in result["aircraft"] if a["hex"] == "ae1460")
    assert shady["track"] is None


def test_a_grounded_altitude_is_absent_rather_than_zero():
    result = aircraft.live_aircraft(client=_client())
    shady = next(a for a in result["aircraft"] if a["hex"] == "ae1460")
    assert shady["alt_ft"] is None


def test_everything_failing_returns_an_honest_blank():
    result = aircraft.live_aircraft(client=_client(fail_all=True))
    assert result["degraded"] is True
    assert result["aircraft"] == []
    assert result["count"] == 0


def test_a_repeat_call_inside_the_ttl_asks_nobody():
    calls = {"n": 0}
    inner = _handler()

    def counting(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return inner(request)

    client = httpx.Client(transport=httpx.MockTransport(counting))
    aircraft.live_aircraft(client=client)
    first = calls["n"]
    assert first > 0
    aircraft.live_aircraft(client=client)
    assert calls["n"] == first


def test_a_blank_answer_is_not_cached():
    # A failed fetch must not pin an empty map in place for the whole window.
    aircraft.live_aircraft(client=_client(fail_all=True))
    result = aircraft.live_aircraft(client=_client())
    assert result["degraded"] is False
    assert result["count"] > 0


def test_presence_never_reaches_the_database():
    """The boundary, enforced rather than described.

    A paragraph saying "this does not persist" survives exactly until somebody
    needs a quick join. An import check does not.
    """
    package = pathlib.Path(aircraft.__file__).parent
    offenders = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if "db_models" in name or name.endswith("app.db") or name == "app.db":
                    offenders.append(f"{path.name} imports {name}")
    assert offenders == [], offenders


def test_a_refused_squawk_check_keeps_the_military_list():
    """The failure that prompted this: one 429 must not cost a hundred aircraft.

    The first live run asked for four endpoints, was rate-limited on the last,
    and threw away a military list that had arrived perfectly well.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        if "/v2/sqk/" in request.url.path:
            return httpx.Response(429, json={"msg": "slow down"})
        return httpx.Response(200, json=MIL)

    result = aircraft.live_aircraft(client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert result["degraded"] is True
    assert result["count"] > 0
    assert "ae6472" in {a["hex"] for a in result["aircraft"]}


def test_the_distress_codes_are_polled_in_turn():
    """Two requests per refresh, not four. Distress lasts minutes; a code
    checked every third refresh is checked often enough."""
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        if request.url.path.endswith("/v2/mil"):
            return httpx.Response(200, json=MIL)
        return httpx.Response(200, json=EMPTY)

    client = httpx.Client(transport=httpx.MockTransport(handle))
    for _ in range(3):
        aircraft._cache.clear()  # expire without resetting the rotation
        aircraft.live_aircraft(client=client)

    squawk_calls = [p for p in asked if "/v2/sqk/" in p]
    assert len(asked) == 6, asked
    assert sorted(squawk_calls) == ["/v2/sqk/7500", "/v2/sqk/7600", "/v2/sqk/7700"]
