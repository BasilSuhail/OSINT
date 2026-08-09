"""The route is a doorway, not a place where work happens."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.enrichment import place_screen as place


@pytest.fixture(autouse=True)
def _clear():
    place.clear_caches()
    yield
    place.clear_caches()
    app.dependency_overrides.clear()


@pytest.fixture
def offline(monkeypatch):
    """Every upstream refuses, which is a state this endpoint must survive.

    Only the module's own outbound client is replaced. Patching httpx itself
    would also gag the test client, which is built on it, and the test would
    then be measuring its own plumbing.
    """

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network in tests")

    monkeypatch.setattr(
        place, "_new_client", lambda: httpx.Client(transport=httpx.MockTransport(refuse))
    )


def test_a_point_returns_its_country_even_with_every_service_down(offline):
    response = TestClient(app).get("/geo/place", params={"lat": 48.8566, "lon": 2.3522})
    assert response.status_code == 200
    body = response.json()
    assert body["country"]["iso2"] == "FR"
    assert body["point"] == {"lat": 48.8566, "lon": 2.3522}
    assert sorted(body["degraded"]) == [
        "government",
        "imagery",
        "next_pass",
        "profile",
        "summary",
    ]


def test_open_water_is_an_answer_not_an_error(offline):
    response = TestClient(app).get("/geo/place", params={"lat": 0, "lon": -140})
    assert response.status_code == 200
    assert response.json()["country"] is None


def test_a_country_code_needs_no_point(offline):
    response = TestClient(app).get("/geo/place", params={"iso": "FR"})
    assert response.status_code == 200
    body = response.json()
    assert body["country"]["iso2"] == "FR"
    assert body["point"] is None
    assert "imagery" not in body["degraded"]


def test_coordinates_out_of_range_are_refused():
    response = TestClient(app).get("/geo/place", params={"lat": 120, "lon": 0})
    assert response.status_code == 422


def test_asking_about_nothing_in_particular_is_refused():
    response = TestClient(app).get("/geo/place")
    assert response.status_code == 422


def test_half_a_point_is_refused():
    response = TestClient(app).get("/geo/place", params={"lat": 48.8566})
    assert response.status_code == 422
