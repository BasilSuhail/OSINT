from typing import Any

import httpx

from app.brain import client


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


def test_generate_json_warm_keep_alive(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse({"response": '{"headline": "quiet"}'})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(client.settings, "brain_keep_alive", "30m")
    monkeypatch.setattr(client.settings, "brain_model", "qwen2.5:1.5b-instruct-q4_K_M")

    result = client.generate_json("hello")
    assert result == {"headline": "quiet"}
    assert captured["json"]["keep_alive"] == "30m"
    assert captured["json"]["model"] == "qwen2.5:1.5b-instruct-q4_K_M"
    assert captured["json"]["options"]["temperature"] == 0


def test_evict_sends_keep_alive_zero(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return _FakeResponse({"response": "{}"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client.evict()
    assert captured["json"]["keep_alive"] == 0


def test_embed_batches_input_and_unloads(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse({"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(client.settings, "embed_model", "nomic-embed-text", raising=False)

    out = client.embed(["first text", "second text"])
    assert captured["url"].endswith("/api/embed")
    assert captured["json"]["model"] == "nomic-embed-text"
    assert captured["json"]["input"] == ["first text", "second text"]
    assert captured["json"]["keep_alive"] == 0
    assert out == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_raises_on_http_failure(monkeypatch):
    class _FailingResponse:
        def raise_for_status(self) -> None:
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: _FailingResponse())
    try:
        client.embed(["text"])
    except httpx.HTTPError:
        pass
    else:
        raise AssertionError("embed swallowed the HTTP failure")


def test_context_window_fits_a_real_qa_prompt():
    """The window must hold the prompt we actually send (#508).

    It did not: `_NUM_CTX` was 2048 while a Q&A prompt measured 4,098 tokens on
    live data, so Ollama discarded half of every request. Because the context
    JSON is ordered stories-then-sensors and truncation drops the front, the
    model lost the stories and kept the sensor block — then denied a Peru
    earthquake that was retrieved as its own source [1], and answered in raw
    JSON because the formatting rules had been cut too.
    """
    assert client._NUM_CTX >= 8192


def test_estimated_tokens_scales_with_length():
    assert client.estimated_tokens("") == 0
    short = client.estimated_tokens("a" * 400)
    long = client.estimated_tokens("a" * 4000)
    assert long > short
    # Roughly four characters per token; exactness is not the point, catching a
    # prompt that has doubled is.
    assert 80 <= short <= 120


def test_oversized_prompt_is_logged_not_silently_truncated(monkeypatch, caplog):
    """Truncation must never again be invisible.

    Ollama silently drops the overflow, so nothing in the logs distinguished a
    healthy answer from one built on half a prompt.
    """

    def fake_post(url, json, timeout):
        return _FakeResponse({"response": '{"answer": "ok"}'})

    monkeypatch.setattr(httpx, "post", fake_post)
    with caplog.at_level("WARNING"):
        client.generate_json("x" * (client._NUM_CTX * 4 + 4000))
    assert any("exceeds" in r.message.lower() for r in caplog.records)


def test_prompt_within_budget_does_not_warn(monkeypatch, caplog):
    def fake_post(url, json, timeout):
        return _FakeResponse({"response": '{"answer": "ok"}'})

    monkeypatch.setattr(httpx, "post", fake_post)
    with caplog.at_level("WARNING"):
        client.generate_json("short prompt")
    assert not [r for r in caplog.records if "exceeds" in r.message.lower()]
