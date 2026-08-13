"""Vessels are drawn and discarded, and say what they are (#954)."""

from __future__ import annotations

import time
from typing import ClassVar

import httpx
import pytest

from app.presence import vessels
from app.presence.vessel_types import category_for, nav_status_for

#: Read from the clock rather than pinned: the layer stamps its own answers
#: with the real time, and a fixture frozen to a date in the past would be
#: measuring how long ago the test was written.
NOW_MS = time.time() * 1000

#: Trimmed from a real answer, keeping the shapes that matter: a cargo ship
#: with everything, a vessel whose static row never arrived, one sending no
#: heading, and one whose position is an hour stale.
POSITIONS = {
    "type": "FeatureCollection",
    "features": [
        {
            "mmsi": 230941570,
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [18.44785, 59.36381]},
            "properties": {
                "mmsi": 230941570,
                "sog": 11.4,
                "cog": 18.9,
                "navStat": 0,
                "heading": 14,
                "timestampExternal": NOW_MS - 5_000,
            },
        },
        {
            "mmsi": 111111111,
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [20.1, 60.2]},
            "properties": {
                "mmsi": 111111111,
                "sog": 0.0,
                "cog": 360.0,
                "navStat": 1,
                "heading": 511,
                "timestampExternal": NOW_MS - 60_000,
            },
        },
        {
            "mmsi": 222222222,
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [21.0, 61.0]},
            "properties": {
                "mmsi": 222222222,
                "sog": 4.0,
                "navStat": 15,
                "timestampExternal": NOW_MS - 4 * 60 * 60 * 1000,
            },
        },
    ],
}

STATICS = [
    {
        "mmsi": 230941570,
        "name": "MERIKUOKKA",
        "callSign": "OI2932",
        "imo": 9123456,
        "shipType": 70,
        "destination": "RAUMA",
    },
    {"mmsi": 222222222, "name": "STALE", "shipType": 80},
]


def _client(*, positions_fail: bool = False, statics_fail: bool = False) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/locations"):
            if positions_fail:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json=POSITIONS)
        if request.url.path.endswith("/vessels"):
            if statics_fail:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json=STATICS)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handle))


@pytest.fixture(autouse=True)
def _clear():
    vessels.clear_cache()
    yield
    vessels.clear_cache()


class TestCategories:
    #: Every code below was counted in one live sample, so these are the rows a
    #: reader will actually see rather than the ones the standard allows.
    @pytest.mark.parametrize(
        ("code", "category"),
        [
            (70, "cargo"),
            (79, "cargo"),
            (80, "tanker"),
            (89, "tanker"),
            (60, "passenger"),
            (69, "passenger"),
            (40, "passenger"),
            (30, "fishing"),
            (36, "pleasure"),
            (37, "pleasure"),
            (31, "service"),
            (33, "service"),
            (50, "service"),
            (52, "service"),
            (55, "service"),
            (90, "other"),
        ],
    )
    def test_reads_the_category_off_the_broadcast_type(self, code, category):
        assert category_for(code) == category

    #: Zero is the standard's "not available". A vessel that will not say what
    #: it is has said something, and it is not "cargo".
    def test_a_vessel_that_said_nothing_is_other(self):
        assert category_for(None) == "other"
        assert category_for(0) == "other"

    def test_names_only_the_statuses_a_reader_would_act_on(self):
        assert nav_status_for(1) == "at anchor"
        assert nav_status_for(5) == "moored"
        assert nav_status_for(7) == "fishing"

    def test_an_undefined_status_stays_silent(self):
        assert nav_status_for(15) is None
        assert nav_status_for(None) is None


class TestTheLayer:
    def test_joins_a_position_to_the_name_of_the_same_mmsi(self):
        answer = vessels.live_vessels(client=_client())
        found = {v["mmsi"]: v for v in answer["vessels"]}
        ship = found[230941570]
        assert ship["name"] == "MERIKUOKKA"
        assert ship["category"] == "cargo"
        assert ship["destination"] == "RAUMA"
        assert ship["nav_status"] == "under way"

    #: A vessel heard once may have a position and no static message yet. It is
    #: really out there, so it is drawn — unnamed and uncategorised, which is
    #: what is actually known about it.
    def test_draws_a_vessel_whose_name_never_arrived(self):
        answer = vessels.live_vessels(client=_client())
        found = {v["mmsi"]: v for v in answer["vessels"]}
        assert 111111111 in found
        assert found[111111111]["name"] is None
        assert found[111111111]["category"] == "other"

    #: 511 means "heading not available" and 360 means "course not available".
    #: Rotating a hull by either would point it somewhere nobody transmitted.
    def test_does_not_turn_the_not_available_codes_into_directions(self):
        answer = vessels.live_vessels(client=_client())
        found = {v["mmsi"]: v for v in answer["vessels"]}
        assert found[111111111]["heading"] is None
        assert found[111111111]["course"] is None
        assert found[230941570]["heading"] == 14.0

    def test_drops_a_position_too_old_to_be_now(self):
        answer = vessels.live_vessels(client=_client())
        assert 222222222 not in {v["mmsi"] for v in answer["vessels"]}

    #: Losing the names is not losing the vessels.
    def test_a_refused_static_request_still_draws_the_fleet(self):
        answer = vessels.live_vessels(client=_client(statics_fail=True))
        assert answer["degraded"] is True
        assert 230941570 in {v["mmsi"] for v in answer["vessels"]}
        assert all(v["name"] is None for v in answer["vessels"])

    def test_a_refused_position_request_is_an_honest_blank(self):
        answer = vessels.live_vessels(client=_client(positions_fail=True))
        assert answer["degraded"] is True
        assert answer["count"] == 0

    def test_an_empty_degraded_answer_is_never_cached(self):
        vessels.live_vessels(client=_client(positions_fail=True))
        answer = vessels.live_vessels(client=_client())
        assert answer["count"] > 0

    def test_one_hull_is_one_mark(self):
        doubled = {"features": POSITIONS["features"] + POSITIONS["features"]}
        merged = vessels.merge(doubled, STATICS, now_ms=NOW_MS)
        assert len({v["mmsi"] for v in merged}) == len(merged)


class TestSpoofedPositions:
    #: The pile-up measured live on 2026-08-13: many hulls on one point, far
    #: inland, at speeds no ship reaches.
    STACK: ClassVar[list[dict]] = [
        {
            "mmsi": 273251530 + i,
            "lat": 57.672007,
            "lon": 32.529673 + i * 0.00001,
            "speed_kt": 46.1,
        }
        for i in range(8)
    ]

    def test_marks_a_pile_of_hulls_on_one_point(self):
        flagged = vessels.flag_spoofed([dict(r) for r in self.STACK])
        assert all(v["position_suspect"] == "stacked" for v in flagged)

    def test_marks_a_speed_no_ship_reaches(self):
        [alone] = vessels.flag_spoofed([{"mmsi": 1, "lat": 59.0, "lon": 21.0, "speed_kt": 46.0}])
        assert alone["position_suspect"] == "speed"

    #: The point of the exercise: ordinary traffic must not be accused.
    def test_leaves_real_traffic_alone(self):
        rows = [
            {"mmsi": 1, "lat": 59.1, "lon": 21.1, "speed_kt": 11.4},
            {"mmsi": 2, "lat": 60.2, "lon": 22.2, "speed_kt": 0.0},
            {"mmsi": 3, "lat": 61.3, "lon": 23.3, "speed_kt": None},
        ]
        flagged = vessels.flag_spoofed(rows)
        assert all(v["position_suspect"] is None for v in flagged)

    #: Two hulls making way and sharing a point is still a coincidence at two.
    def test_two_hulls_on_one_point_are_not_accused(self):
        rows = [
            {"mmsi": 1, "lat": 60.1, "lon": 24.9, "speed_kt": 12.0},
            {"mmsi": 2, "lat": 60.1, "lon": 24.9, "speed_kt": 12.0},
        ]
        assert all(v["position_suspect"] is None for v in vessels.flag_spoofed(rows))

    #: The false positive that the first version of this test produced: a row
    #: of pilot boats tied up at one pier rounds to one set of coordinates.
    #: Moored craft genuinely do share a point, so only vessels making way are
    #: counted into a pile-up.
    def test_a_pier_full_of_moored_craft_is_not_a_spoof(self):
        rows = [{"mmsi": i, "lat": 65.673517, "lon": 24.514805, "speed_kt": 0.0} for i in range(6)]
        assert all(v["position_suspect"] is None for v in vessels.flag_spoofed(rows))

    #: Flagged, never dropped. A transmitter claiming to be a ship in a forest
    #: is worth more to a reader than the traffic around it.
    def test_a_suspect_vessel_is_still_drawn(self):
        flagged = vessels.flag_spoofed([dict(r) for r in self.STACK])
        assert len(flagged) == len(self.STACK)

    def test_the_layer_carries_the_flag_and_the_accuracy_bit(self):
        answer = vessels.live_vessels(client=_client())
        found = {v["mmsi"]: v for v in answer["vessels"]}
        assert found[230941570]["position_suspect"] is None
        assert "position_accurate" in found[230941570]
