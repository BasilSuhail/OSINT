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
