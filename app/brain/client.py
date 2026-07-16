"""The brain's Ollama client (#409) — localhost HTTP via httpx, nothing leaves.

Same discipline as app/validator/client.py, but with an adaptive keep_alive so
the small model stays warm between the frequent narrate ticks, plus an evict()
that unloads it immediately (keep_alive=0) the moment a heavy job needs the RAM.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from app.settings import settings

_TIMEOUT_S: float = 120.0
_NUM_CTX: int = 2048


def generate_json(
    prompt: str, *, model: str | None = None, keep_alive: str | None = None
) -> dict[str, Any]:
    """One prompt → parsed JSON dict. Raises on HTTP or JSON failure."""
    response = httpx.post(
        f"{settings.ollama_url}/api/generate",
        json={
            "model": model or settings.brain_model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "think": False,
            "keep_alive": keep_alive or settings.brain_keep_alive,
            "options": {"temperature": 0, "num_ctx": _NUM_CTX},
        },
        timeout=_TIMEOUT_S,
    )
    response.raise_for_status()
    return json.loads(response.json()["response"])


def generate_text_stream(
    prompt: str, *, model: str | None = None, keep_alive: str | None = None
) -> Iterator[str]:
    """Yield Ollama response text chunks for a plain-text answer prompt."""
    with httpx.stream(
        "POST",
        f"{settings.ollama_url}/api/generate",
        json={
            "model": model or settings.brain_model,
            "prompt": prompt,
            "stream": True,
            "think": False,
            "keep_alive": keep_alive or settings.brain_keep_alive,
            "options": {"temperature": 0, "num_ctx": _NUM_CTX},
        },
        timeout=_TIMEOUT_S,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            payload = json.loads(line)
            chunk = payload.get("response")
            if isinstance(chunk, str) and chunk:
                yield chunk
            if payload.get("done"):
                break


def evict(*, model: str | None = None) -> None:
    """Unload the model now: an empty generate with keep_alive=0."""
    response = httpx.post(
        f"{settings.ollama_url}/api/generate",
        json={
            "model": model or settings.brain_model,
            "prompt": "",
            "stream": False,
            "keep_alive": 0,
        },
        timeout=_TIMEOUT_S,
    )
    response.raise_for_status()
