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
