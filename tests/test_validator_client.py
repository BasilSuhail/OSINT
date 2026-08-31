from typing import Any

import httpx

from app.validator import client


class _FakeResponse:
    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return {"response": "{}"}


def test_generate_json_sends_configured_request_threads(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(client.settings, "ollama_request_num_thread", 3)

    client.generate_json("hello")

    assert captured["json"]["options"]["num_thread"] == 3


def test_generate_json_leaves_thread_selection_automatic_at_zero(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(client.settings, "ollama_request_num_thread", 0)

    client.generate_json("hello")

    assert "num_thread" not in captured["json"]["options"]
