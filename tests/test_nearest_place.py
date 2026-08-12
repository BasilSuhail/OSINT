"""The settlement a right-click is standing in, or near (#932).

A point is smaller than a country, and the screen never named the smaller
thing. Two questions decide whether this block is useful or noise: which name
to use for a place that OSM describes at several levels, and how far away is
too far to claim the reader is anywhere near it.
"""

from __future__ import annotations

import httpx
import pytest

from app.enrichment.nearest_place import MAX_DISTANCE_KM, nearest_place, read_address


def _reverse(address: dict, *, lat: str = "48.8566", lon: str = "2.3522") -> dict:
    return {"lat": lat, "lon": lon, "address": address, "extratags": {}}


def test_a_city_is_read_from_the_address() -> None:
    found = read_address(_reverse({"city": "Paris", "state": "Île-de-France"}))
    assert found["name"] == "Paris"
    assert found["region"] == "Île-de-France"


def test_a_town_answers_when_there_is_no_city() -> None:
    found = read_address(_reverse({"town": "Ballater", "state": "Scotland"}))
    assert found["name"] == "Ballater"


def test_a_village_answers_when_there_is_neither() -> None:
    found = read_address(_reverse({"village": "Braemar", "county": "Aberdeenshire"}))
    assert found["name"] == "Braemar"
    assert found["region"] == "Aberdeenshire"


def test_the_most_specific_settlement_wins() -> None:
    """OSM often returns several levels at once. A village inside a county
    inside a state is three true answers, and the smallest is the one the
    reader clicked on."""
    found = read_address(_reverse({"city": "Aberdeen", "village": "Cults", "state": "Scotland"}))
    assert found["name"] == "Cults"


def test_a_place_with_no_settlement_at_all_is_nothing() -> None:
    assert read_address(_reverse({"country": "France"})) is None


def test_the_wikidata_id_is_carried_when_osm_has_one() -> None:
    body = _reverse({"city": "Paris"})
    body["extratags"] = {"wikidata": "Q90"}
    assert read_address(body)["qid"] == "Q90"


def test_a_missing_wikidata_id_is_normal() -> None:
    assert read_address(_reverse({"city": "Paris"}))["qid"] is None


def test_distance_is_measured_from_the_point_that_was_clicked() -> None:
    """Nominatim answers with the settlement's own coordinate, not the query's,
    so the distance is real and worth showing: it tells the reader whether the
    weather above is about their point or about somewhere down the road."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_reverse({"city": "Paris"}, lat="48.8566", lon="2.3522"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    found = nearest_place(client, 48.9000, 2.3522)
    assert found is not None
    assert 4.5 < found["distance_km"] < 5.5


def test_a_settlement_beyond_the_cap_is_not_claimed_as_nearby() -> None:
    """Naming a city 400 km away reads as an error rather than as a fact. The
    weather block does not depend on this one and still renders."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_reverse({"city": "Reykjavík"}, lat="64.1466", lon="-21.9426")
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert nearest_place(client, 48.8566, 2.3522) is None


def test_an_empty_answer_is_nothing_rather_than_a_failure() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "Unable to geocode"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert nearest_place(client, 0.0, -140.0) is None


def test_an_upstream_error_is_raised_so_the_block_degrades() -> None:
    """A 500 is not "no city here". The screen distinguishes a place with no
    settlement from a lookup that could not be made, and only one of those is
    worth an "unavailable" line."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        nearest_place(client, 48.8566, 2.3522)


def test_the_cap_is_a_hundred_kilometres() -> None:
    assert MAX_DISTANCE_KM == 100
