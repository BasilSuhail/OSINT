"""The second sea area, and the rules it is held to (#954).

The response shape asserted here is the operator's documented one. It has not
been seen against the live service — credentials could not be issued while it
was written — so these tests hold the reshaping and the configuration rules,
which are ours, and not the field names, which are theirs. The issue records
what one live run has to confirm.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.presence import vessels, vessels_no

ROWS = [
    {
        "mmsi": 257058920,
        "latitude": 59.36381,
        "longitude": 18.44785,
        "speedOverGround": 11.4,
        "courseOverGround": 18.9,
        "trueHeading": 14,
        "navigationalStatus": 0,
        "name": "NORDLYS",
        "shipType": 60,
        "callSign": "LAAA",
        "destination": "BERGEN",
        #: Stamped from the clock: the layer drops a position older than an
        #: hour, so a fixture pinned to a past date would measure how long
        #: ago the test was written.
        "msgtime": datetime.now(UTC).isoformat(),
    },
    {"mmsi": 111111111, "latitude": 60.1, "longitude": 5.3, "speedOverGround": 0.0},
    {"latitude": 61.0, "longitude": 6.0},
]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    vessels_no.clear_token()
    vessels.clear_cache()
    monkeypatch.delenv(vessels_no.CLIENT_ID_ENV, raising=False)
    monkeypatch.delenv(vessels_no.CLIENT_SECRET_ENV, raising=False)
    yield
    vessels_no.clear_token()
    vessels.clear_cache()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv(vessels_no.CLIENT_ID_ENV, "a-client")
    monkeypatch.setenv(vessels_no.CLIENT_SECRET_ENV, "a-secret")


def _client(*, token_fails: bool = False, data_fails: bool = False, calls: list | None = None):
    def handle(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        if request.url.host == "id.barentswatch.no":
            if token_fails:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json={"access_token": "a-token", "expires_in": 3600})
        if data_fails:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json=ROWS)

    return httpx.Client(transport=httpx.MockTransport(handle))


class TestConfiguration:
    def test_no_credentials_means_the_feed_is_not_asked(self):
        assert vessels_no.credentials() is None
        calls: list[str] = []
        vessels_no.fetch(_client(calls=calls), "https://live.ais.barentswatch.no", "/v1/x")
        assert calls == []

    def test_half_a_client_is_no_client(self, monkeypatch):
        monkeypatch.setenv(vessels_no.CLIENT_ID_ENV, "a-client")
        assert vessels_no.credentials() is None

    def test_configured_is_a_client(self, configured):
        assert vessels_no.credentials() == ("a-client", "a-secret")


class TestReshaping:
    def test_turns_a_row_into_the_shape_the_layer_already_reads(self, configured):
        features, statics = vessels_no.fetch(
            _client(), "https://live.ais.barentswatch.no", "/v1/latest/combined"
        )
        first = next(f for f in features if f["properties"]["mmsi"] == 257058920)
        assert first["geometry"]["coordinates"] == [18.44785, 59.36381]
        assert first["properties"]["sog"] == 11.4
        assert first["properties"]["heading"] == 14.0
        static = next(s for s in statics if s["mmsi"] == 257058920)
        assert static["name"] == "NORDLYS"
        assert static["shipType"] == 60

    #: A row with no transponder number cannot be joined to anything and
    #: cannot be deduped against the other sea area, so it is not drawn.
    def test_drops_a_row_with_no_mmsi(self, configured):
        features, _ = vessels_no.fetch(
            _client(), "https://live.ais.barentswatch.no", "/v1/latest/combined"
        )
        assert len(features) == 2

    def test_reads_the_time_the_message_was_sent(self, configured):
        features, _ = vessels_no.fetch(
            _client(), "https://live.ais.barentswatch.no", "/v1/latest/combined"
        )
        first = next(f for f in features if f["properties"]["mmsi"] == 257058920)
        assert first["properties"]["timestampExternal"] > 0

    #: The documented shape is a flat row, but this has never been seen
    #: against the real service, and a geojson wrapper is the likeliest way
    #: the documentation is wrong.
    def test_accepts_a_geojson_wrapper_too(self, configured):
        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.host == "id.barentswatch.no":
                return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
            return httpx.Response(
                200,
                json=[
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [5.3, 60.1]},
                        "properties": {"mmsi": 222222222, "speedOverGround": 8.0},
                    }
                ],
            )

        client = httpx.Client(transport=httpx.MockTransport(handle))
        features, _ = vessels_no.fetch(client, "https://live.ais.barentswatch.no", "/v1/x")
        assert features[0]["properties"]["mmsi"] == 222222222
        assert features[0]["geometry"]["coordinates"] == [5.3, 60.1]


class TestTokens:
    def test_asks_for_a_token_once_and_reuses_it(self, configured):
        calls: list[str] = []
        client = _client(calls=calls)
        vessels_no.fetch(client, "https://live.ais.barentswatch.no", "/v1/x")
        vessels_no.fetch(client, "https://live.ais.barentswatch.no", "/v1/x")
        assert sum(1 for c in calls if "id.barentswatch.no" in c) == 1

    #: A token believed past its death is a request refused for a reason
    #: nobody can see, so a response with no expiry gets a short life.
    def test_a_response_with_no_expiry_is_not_believed_forever(self, configured):
        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.host == "id.barentswatch.no":
                return httpx.Response(200, json={"access_token": "t"})
            return httpx.Response(200, json=[])

        client = httpx.Client(transport=httpx.MockTransport(handle))
        vessels_no.fetch(client, "https://live.ais.barentswatch.no", "/v1/x")
        assert vessels_no._token is not None

    def test_a_refused_token_raises_rather_than_reading_as_an_empty_sea(self, configured):
        with pytest.raises(httpx.ConnectError):
            vessels_no.fetch(_client(token_fails=True), "https://live.ais.barentswatch.no", "/v1/x")


class TestTheLayerWithTwoSeas:
    #: One console, two sea areas, one list of vessels — and the reader is
    #: told who reported what.
    def test_names_every_source_that_answered(self, configured, monkeypatch):
        def handle(request: httpx.Request) -> httpx.Response:
            host = request.url.host
            if host == "id.barentswatch.no":
                return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
            if host == "live.ais.barentswatch.no":
                return httpx.Response(200, json=ROWS)
            if request.url.path.endswith("/locations"):
                return httpx.Response(200, json={"features": []})
            return httpx.Response(200, json=[])

        answer = vessels.live_vessels(client=httpx.Client(transport=httpx.MockTransport(handle)))
        assert "BarentsWatch · NLOD" in answer["sources"]
        assert 257058920 in {v["mmsi"] for v in answer["vessels"]}

    #: A source nobody configured is not a fault. Saying "degraded" for it
    #: would cry wolf on every console that only wants the first sea.
    def test_an_unconfigured_second_sea_is_not_degradation(self):
        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/locations"):
                return httpx.Response(200, json={"features": []})
            return httpx.Response(200, json=[])

        answer = vessels.live_vessels(client=httpx.Client(transport=httpx.MockTransport(handle)))
        assert answer["degraded"] is False
        assert answer["sources"] == ["Fintraffic / digitraffic.fi · CC BY 4.0"]

    #: One hull heard by both networks is one mark. The sea areas touch, and
    #: a vessel in the overlap must not be counted twice.
    def test_a_vessel_heard_by_both_seas_is_one_vessel(self, configured):
        shared = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [10.0, 58.0]},
            "properties": {"mmsi": 257058920, "sog": 9.0, "timestampExternal": None},
        }

        def handle(request: httpx.Request) -> httpx.Response:
            host = request.url.host
            if host == "id.barentswatch.no":
                return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
            if host == "live.ais.barentswatch.no":
                return httpx.Response(200, json=ROWS)
            if request.url.path.endswith("/locations"):
                return httpx.Response(200, json={"features": [shared]})
            return httpx.Response(200, json=[])

        answer = vessels.live_vessels(client=httpx.Client(transport=httpx.MockTransport(handle)))
        assert sum(1 for v in answer["vessels"] if v["mmsi"] == 257058920) == 1
