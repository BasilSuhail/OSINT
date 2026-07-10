"""Ollama client — plain localhost HTTP via httpx, nothing leaves the machine.

`format: json` forces valid JSON, `think: false` disables the thinking
channel (qwen3.5 otherwise puts everything there), `temperature 0` for
determinism, and a short keep_alive keeps the model warm through a nightly
batch and unloaded the rest of the day — the 8 GB Pi never carries it idle.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.settings import settings

_TIMEOUT_S: float = 120.0
_KEEP_ALIVE: str = "5m"
#: The claim prompt is a few hundred tokens; capping the context keeps the
#: loaded model's KV cache small instead of reserving the default window (#384).
_NUM_CTX: int = 2048


def generate_json(prompt: str, *, model: str | None = None) -> dict[str, Any]:
    """One prompt → parsed JSON dict. Raises on HTTP or JSON failure."""
    response = httpx.post(
        f"{settings.ollama_url}/api/generate",
        json={
            "model": model or settings.ollama_model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "think": False,
            "keep_alive": _KEEP_ALIVE,
            "options": {"temperature": 0, "num_ctx": _NUM_CTX},
        },
        timeout=_TIMEOUT_S,
    )
    response.raise_for_status()
    return json.loads(response.json()["response"])
