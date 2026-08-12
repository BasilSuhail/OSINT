"""The route is a doorway, not a place where work happens (#934)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.presence import upcoming as up


@pytest.fixture(autouse=True)
def _clear():
    up.clear_cache()
    yield
    up.clear_cache()
    app.dependency_overrides.clear()


@pytest.fixture
def answering(monkeypatch):
    """Wikidata answers with one election in each of two countries."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": {
                    "bindings": [
                        {
                            "itemLabel": {"value": "2026 Swedish general election"},
                            "begin": {"value": "2026-09-13T00:00:00Z"},
                            "iso": {"value": "SE"},
                            "countryLabel": {"value": "Sweden"},
                            "typeLabel": {"value": "general election"},
                        },
                        {
                            "itemLabel": {"value": "2026 Haitian presidential election"},
                            "begin": {"value": "2026-08-30T00:00:00Z"},
                            "iso": {"value": "HT"},
                            "countryLabel": {"value": "Haiti"},
                            "typeLabel": {"value": "presidential election"},
                        },
                    ]
                }
            },
        )

    monkeypatch.setattr(
        up, "_new_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_the_calendar_answers_soonest_first(answering):
    response = TestClient(app).get("/presence/upcoming")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert [entry["iso"] for entry in body["entries"]] == ["HT", "SE"]
    assert body["degraded"] is False


def test_a_country_filter_narrows_the_same_answer(answering):
    body = TestClient(app).get("/presence/upcoming", params={"iso": "se"}).json()
    assert body["count"] == 1
    assert body["entries"][0]["country"] == "Sweden"


def test_a_country_with_nothing_scheduled_is_an_empty_list_not_an_error(answering):
    response = TestClient(app).get("/presence/upcoming", params={"iso": "FR"})
    assert response.status_code == 200
    assert response.json()["entries"] == []


def test_an_impossible_window_is_refused_rather_than_asked_for():
    assert TestClient(app).get("/presence/upcoming", params={"days": 0}).status_code == 422
    assert TestClient(app).get("/presence/upcoming", params={"days": 900}).status_code == 422


def test_the_upstream_being_down_is_an_empty_calendar_that_says_so(monkeypatch):
    def refuse(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network in tests")

    monkeypatch.setattr(
        up, "_new_client", lambda: httpx.Client(transport=httpx.MockTransport(refuse))
    )
    body = TestClient(app).get("/presence/upcoming").json()
    assert body["entries"] == []
    assert body["degraded"] is True
