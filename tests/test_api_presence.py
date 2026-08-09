"""The presence route is a doorway. Nothing happens here."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.presence import aircraft


@pytest.fixture(autouse=True)
def _clear():
    aircraft.clear_cache()
    yield
    aircraft.clear_cache()
    app.dependency_overrides.clear()


@pytest.fixture
def offline(monkeypatch):
    """Only this module's outbound client is replaced.

    Patching httpx would also gag the test client, which is built on it.
    """

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network in tests")

    monkeypatch.setattr(
        aircraft, "_new_client", lambda: httpx.Client(transport=httpx.MockTransport(refuse))
    )


def test_the_map_gets_an_empty_picture_when_nothing_answers(offline):
    response = TestClient(app).get("/presence/aircraft")
    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True
    assert body["aircraft"] == []


def test_the_answer_carries_its_own_age(offline):
    body = TestClient(app).get("/presence/aircraft").json()
    assert body["fetched_at"].endswith("+00:00")
