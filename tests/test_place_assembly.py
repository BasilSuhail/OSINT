"""Four third-party services will not all answer every time, and a screen that
500s because one of them was slow is worse than a screen missing one block."""

from __future__ import annotations

import httpx
import pytest

from app.enrichment import place_screen as place

#: Real published elements, so the assembly test never reaches the network.
ELEMENTS = """SENTINEL-2A
1 40697U 15028A   26221.29162428 -.00000152  00000+0 -41436-4 0  9990
2 40697  98.5658 295.3818 0001356  90.7501 269.3838 14.30819839581326
"""

PARIS = (48.8566, 2.3522)
OCEAN = (0.0, -140.0)

_FORECAST = {
    "properties": {
        "timeseries": [
            {
                "time": "2026-08-12T09:00:00Z",
                "data": {
                    "instant": {
                        "details": {
                            "air_temperature": 21.4,
                            "wind_speed": 2.6,
                            "wind_from_direction": 190.0,
                            "relative_humidity": 58.0,
                        }
                    },
                    "next_1_hours": {"summary": {"symbol_code": "fair_day"}},
                },
            },
            {
                "time": "2026-08-12T10:00:00Z",
                "data": {"instant": {"details": {"air_temperature": 24.9}}},
            },
        ]
    }
}

_STAC_ITEM = {
    "features": [
        {
            "id": "S2_TEST_ITEM",
            "properties": {"datetime": "2026-07-30T11:33:21Z", "eo:cloud_cover": 12.5},
            "assets": {},
        }
    ]
}


def _handler(*, fail: set[str] | None = None):
    failed = fail or set()

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "wikidata" in url and "wd%3AQ" in url:
            # The settlement's population (#932): a different query against the
            # same service, and it fails on its own.
            if "city-pop" in failed:
                raise httpx.ConnectError("refused")
            return httpx.Response(
                200, json={"results": {"bindings": [{"population": {"value": "2102650"}}]}}
            )
        if "nominatim" in url:
            if "city" in failed:
                raise httpx.ConnectError("refused")
            if "nocity" in failed:
                return httpx.Response(200, json={"error": "Unable to geocode"})
            return httpx.Response(
                200,
                json={
                    "lat": "48.8566",
                    "lon": "2.3522",
                    "address": {"city": "Paris", "state": "Île-de-France"},
                    "extratags": {"wikidata": "Q90"},
                },
            )
        if "api.met.no" in url:
            if "weather" in failed:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json=_FORECAST)
        if "wikidata" in url:
            if "facts" in failed:
                raise httpx.ConnectError("refused")
            if "empty" in failed:
                return httpx.Response(200, json={"results": {"bindings": []}})
            return httpx.Response(
                200,
                json={
                    "results": {
                        "bindings": [
                            {
                                "government": {"value": "semi-presidential system"},
                                "headOfState": {"value": "the office holder"},
                                "headOfGovernment": {"value": "the office holder"},
                                "capital": {"value": "Paris"},
                                "population": {"value": "68605616"},
                                "area": {"value": "643801"},
                                "languages": {"value": "French"},
                                "currencies": {"value": "EUR|XPF"},
                            }
                        ]
                    }
                },
            )
        if "wikipedia" in url:
            if "summary" in failed:
                raise httpx.ConnectError("refused")
            return httpx.Response(
                200,
                json={
                    "title": "France",
                    "extract": "A country in Western Europe.",
                    "content_urls": {"desktop": {"page": "https://example.invalid/wiki"}},
                    "thumbnail": {"source": "https://example.invalid/thumb.png"},
                },
            )
        if "celestrak" in url:
            if "pass" in failed:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, text=ELEMENTS)
        if "planetarycomputer" in url:
            if "imagery" in failed:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json=_STAC_ITEM)
        raise AssertionError(f"unexpected request to {url}")

    return handle


def _client(**kwargs) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(_handler(**kwargs)))


@pytest.fixture(autouse=True)
def _clear():
    place.clear_caches()
    yield
    place.clear_caches()


def test_every_source_answering_leaves_nothing_degraded():
    answer = place.describe_place(*PARIS, client=_client())
    assert answer["country"]["iso2"] == "FR"
    assert answer["profile"]["capital"] == "Paris"
    assert answer["profile"]["languages"] == ["French"]
    assert answer["profile"]["currencies"] == ["EUR", "XPF"]
    assert answer["profile"]["population"] == 68_605_616
    assert answer["government"]["type"] == "semi-presidential system"
    assert answer["summary"]["extract"].startswith("A country")
    assert answer["imagery"]["cloud_cover_pct"] == 12.5
    assert answer["imagery"]["item_id"] == "S2_TEST_ITEM"
    assert answer["degraded"] == []


def test_one_source_failing_leaves_the_others_standing():
    answer = place.describe_place(*PARIS, client=_client(fail={"summary"}))
    assert answer["summary"] is None
    assert answer["degraded"] == ["summary"]
    assert answer["profile"]["capital"] == "Paris"
    assert answer["imagery"] is not None


def test_the_two_blocks_from_one_query_go_missing_together():
    answer = place.describe_place(*PARIS, client=_client(fail={"facts"}))
    assert answer["profile"] is None
    assert answer["government"] is None
    assert sorted(answer["degraded"]) == ["government", "profile"]
    assert answer["summary"] is not None


def test_an_answer_with_no_rows_is_a_failure_not_an_empty_screen():
    answer = place.describe_place(*PARIS, client=_client(fail={"empty"}))
    assert answer["profile"] is None
    assert sorted(answer["degraded"]) == ["government", "profile"]


def test_all_sources_failing_still_returns_the_country():
    answer = place.describe_place(
        *PARIS, client=_client(fail={"facts", "summary", "imagery", "pass"})
    )
    assert answer["country"]["iso2"] == "FR"
    assert "government" in answer["degraded"]
    assert "imagery" in answer["degraded"]


def test_open_ocean_has_no_country_but_still_asks_for_a_photograph():
    answer = place.describe_place(*OCEAN, client=_client())
    assert answer["country"] is None
    assert answer["imagery"] is not None
    assert "profile" in answer["degraded"]


def test_the_point_is_named_before_the_country_is():
    answer = place.describe_place(*PARIS, client=_client())
    assert answer["city"]["name"] == "Paris"
    assert answer["city"]["region"] == "Île-de-France"
    assert answer["city"]["population"] == 2_102_650
    assert answer["city"]["distance_km"] == 0.0
    assert answer["weather"]["temperature_c"] == 21.4
    assert answer["weather"]["conditions"] == "Fair"
    assert answer["degraded"] == []


def test_weather_is_about_the_coordinate_so_it_survives_having_no_city():
    """Open desert and open ocean have conditions. The screen says what they
    are, and says nothing about a town, because there is not one."""
    answer = place.describe_place(*OCEAN, client=_client(fail={"nocity"}))
    assert answer["city"] is None
    assert answer["weather"]["temperature_c"] == 21.4
    assert "city" not in answer["degraded"]


def test_a_place_with_nobody_near_it_is_not_a_degraded_block():
    """ "No settlement within a hundred kilometres" is an answer. An
    "unavailable" line would tell the reader to try again, for nothing."""
    answer = place.describe_place(*PARIS, client=_client(fail={"nocity"}))
    assert answer["city"] is None
    assert "city" not in answer["degraded"]


def test_a_failed_lookup_is_degraded_rather_than_silently_empty():
    answer = place.describe_place(*PARIS, client=_client(fail={"city"}))
    assert answer["city"] is None
    assert "city" in answer["degraded"]
    assert answer["weather"] is not None


def test_weather_failing_costs_the_weather_and_nothing_else():
    answer = place.describe_place(*PARIS, client=_client(fail={"weather"}))
    assert answer["weather"] is None
    assert answer["degraded"] == ["weather"]
    assert answer["city"]["name"] == "Paris"


def test_the_city_survives_its_population_being_unavailable():
    """The name of the town is the block. A second service being slow must not
    take it off the screen."""
    answer = place.describe_place(*PARIS, client=_client(fail={"city-pop"}))
    assert answer["city"]["name"] == "Paris"
    assert answer["city"]["population"] is None
    assert "city" not in answer["degraded"]


def test_a_country_asked_for_by_code_has_no_city_and_no_weather():
    """There is no point behind the country chip, so there is nowhere to ask
    about. Inventing a centroid would put a capital's weather on a screen about
    a whole country."""
    answer = place.describe_place_by_country("FR", client=_client())
    assert answer["city"] is None
    assert answer["weather"] is None
    assert "city" not in answer["degraded"]
    assert "weather" not in answer["degraded"]


def test_a_point_beside_a_border_says_so():
    answer = place.describe_place(47.5586, 7.5886, client=_client())
    assert answer["country"]["near_border"] is True


def test_a_country_asked_for_by_code_has_no_photograph():
    answer = place.describe_place_by_country("FR", client=_client())
    assert answer["country"]["iso2"] == "FR"
    assert answer["point"] is None
    assert answer["imagery"] is None
    assert "imagery" not in answer["degraded"]


def test_a_repeat_call_inside_the_ttl_does_not_ask_again():
    calls = {"n": 0}
    inner = _handler()

    def counting(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return inner(request)

    client = httpx.Client(transport=httpx.MockTransport(counting))
    place.describe_place(*PARIS, client=client)
    first = calls["n"]
    assert first > 0
    place.describe_place(*PARIS, client=client)
    assert calls["n"] == first
