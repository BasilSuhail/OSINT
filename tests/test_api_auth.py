"""Who may talk to this API, and how often (#824).

Measured on a running stack: the API, Postgres and Redis were all listening on
every interface, and the API answered anything that reached the port —
including `POST /brain/ask`, which spends local model inference per call.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api as api
from app import api_auth
from app.api import app, get_session

TOKEN = "test-token-value"


@pytest.fixture(autouse=True)
def _clean():
    api_auth.ask_limiter._hits.clear()
    yield
    app.dependency_overrides.clear()
    api_auth.ask_limiter._hits.clear()


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(api_auth.settings, "api_auth_token", TOKEN)
    return TestClient(app)


class TestWithATokenConfigured:
    def test_an_unauthenticated_request_is_refused(self, secured, db_session):
        app.dependency_overrides[get_session] = lambda: db_session
        assert secured.get("/events").status_code == 401

    def test_the_api_key_header_is_accepted(self, secured, db_session):
        app.dependency_overrides[get_session] = lambda: db_session
        assert secured.get("/events", headers={"X-API-Key": TOKEN}).status_code == 200

    def test_a_bearer_token_is_accepted(self, secured, db_session):
        app.dependency_overrides[get_session] = lambda: db_session
        headers = {"Authorization": f"Bearer {TOKEN}"}
        assert secured.get("/events", headers=headers).status_code == 200

    def test_a_wrong_token_is_refused(self, secured, db_session):
        app.dependency_overrides[get_session] = lambda: db_session
        assert secured.get("/events", headers={"X-API-Key": "nope"}).status_code == 401

    def test_a_prefix_of_the_token_is_refused(self, secured, db_session):
        """The comparison is constant-time; this asserts the behaviour that
        makes it worth having."""
        app.dependency_overrides[get_session] = lambda: db_session
        headers = {"X-API-Key": TOKEN[:-1]}
        assert secured.get("/events", headers=headers).status_code == 401

    def test_the_liveness_probe_still_answers(self, secured):
        """A probe that needs a credential cannot tell down from
        misconfigured, which is the one job it has."""
        assert secured.get("/health").status_code == 200

    def test_every_route_is_covered_not_just_the_ones_someone_remembered(self, secured, db_session):
        app.dependency_overrides[get_session] = lambda: db_session
        for path in ("/events", "/scores", "/events/stats", "/stories/top", "/search?q=edinburgh"):
            assert secured.get(path).status_code == 401, path


class TestWithoutAToken:
    def test_the_api_stays_open(self, monkeypatch, db_session):
        monkeypatch.setattr(api_auth.settings, "api_auth_token", "")
        app.dependency_overrides[get_session] = lambda: db_session
        assert TestClient(app).get("/events").status_code == 200

    def test_startup_says_so(self, monkeypatch, caplog):
        monkeypatch.setattr(api_auth.settings, "api_auth_token", "")
        with caplog.at_level("WARNING"):
            api_auth.log_exposure()
        assert "UNAUTHENTICATED" in caplog.text

    def test_a_configured_api_says_that_instead(self, monkeypatch, caplog):
        monkeypatch.setattr(api_auth.settings, "api_auth_token", TOKEN)
        with caplog.at_level("INFO"):
            api_auth.log_exposure()
        assert "authentication enabled" in caplog.text


class TestInferenceRateLimit:
    def test_a_burst_is_refused_after_the_limit(self, monkeypatch, db_session):
        monkeypatch.setattr(api_auth.settings, "api_auth_token", "")
        monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
        monkeypatch.setattr(
            api.qa,
            "build_qa_context",
            lambda session, **_kw: {"stories": []},
        )
        monkeypatch.setattr(api.client, "generate_json", lambda prompt, **kw: {"answer": "No."})
        app.dependency_overrides[get_session] = lambda: db_session
        client = TestClient(app)

        codes = [
            client.post("/brain/ask", json={"question": "what is loudest?"}).status_code
            for _ in range(api_auth.ASK_LIMIT + 2)
        ]
        assert codes[: api_auth.ASK_LIMIT] == [200] * api_auth.ASK_LIMIT
        assert codes[-1] == 429

    def test_reads_are_not_rate_limited(self, monkeypatch, db_session):
        """A read is cheap and idempotent. Limiting it would trade an outage
        for a different outage."""
        monkeypatch.setattr(api_auth.settings, "api_auth_token", "")
        app.dependency_overrides[get_session] = lambda: db_session
        client = TestClient(app)
        codes = {client.get("/events").status_code for _ in range(api_auth.ASK_LIMIT + 5)}
        assert codes == {200}

    def test_the_window_lets_a_caller_back_in(self):
        limiter = api_auth.RateLimiter(limit=2, window_seconds=60.0)
        assert limiter.check("a", now=0.0)
        assert limiter.check("a", now=1.0)
        assert not limiter.check("a", now=2.0)
        assert limiter.check("a", now=61.5)

    def test_callers_are_counted_separately(self):
        limiter = api_auth.RateLimiter(limit=1, window_seconds=60.0)
        assert limiter.check("a", now=0.0)
        assert not limiter.check("a", now=0.1)
        assert limiter.check("b", now=0.2)


class TestTheStreamException:
    def test_the_stream_accepts_its_token_in_the_query(self, secured):
        """`EventSource` cannot send headers. The exception is deliberate,
        narrow, and the only place a token may travel in a URL."""
        request = _request("/stream", query="token=" + TOKEN)
        assert api_auth.presented_token(request) == TOKEN

    def test_no_other_endpoint_accepts_one_there(self, secured):
        request = _request("/events", query="token=" + TOKEN)
        assert api_auth.presented_token(request) is None


def _request(path: str, *, query: str = ""):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "server": ("testserver", 80),
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [],
        "client": ("127.0.0.1", 1234),
    }
    return Request(scope)
