"""The brain's Ollama client (#409) — localhost HTTP via httpx, nothing leaves.

Same discipline as app/validator/client.py, but with an adaptive keep_alive so
the small model stays warm between the frequent narrate ticks, plus an evict()
that unloads it immediately (keep_alive=0) the moment a heavy job needs the RAM.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)

_TIMEOUT_S: float = 120.0

#: Context window for every local generate call.
#:
#: Was 2048 (#384, protecting the Pi's RAM). A Q&A prompt measures ~4,100
#: tokens on live data, so Ollama silently discarded half of every request:
#: `prompt_eval_count` came back as exactly 2048 against a 4,098-token prompt.
#: The context JSON is ordered stories-then-sensors and truncation drops the
#: front, so the model lost the stories and kept the sensor block — it denied a
#: Peru earthquake that had been retrieved as its own source [1], and replied in
#: raw JSON because the formatting rules had been cut away too (#508).
#:
#: Measured cost of the window itself, model resident:
#:   num_ctx=2048 -> 5.7 GB   4096 -> 5.8 GB   8192 -> 6.0 GB
#: The 4B weights dominate; the KV cache is roughly 100 MB per 2k tokens. The
#: old cap was defending ~300 MB while destroying half of every prompt.
#:
#: 8192 rather than 4096 because prompts carry conversation history and grow
#: turn over turn — a 4,100-token first turn leaves no headroom at 4096.
_NUM_CTX: int = 8192


def estimated_tokens(text: str) -> int:
    """Rough token count for a prompt: about four characters per token.

    Deliberately an estimate. Ollama exposes no tokenizer endpoint, and the
    purpose here is spotting a prompt that has outgrown the window, not billing
    accuracy.
    """
    return len(text) // 4


def _warn_if_oversized(prompt: str, model: str) -> None:
    """Truncation is silent in Ollama; this makes it visible.

    Nothing in the logs used to distinguish a healthy answer from one built on
    half a prompt — the model just quietly got less context and behaved worse.
    """
    tokens = estimated_tokens(prompt)
    if tokens > _NUM_CTX:
        logger.warning(
            "prompt for %s is ~%d tokens and exceeds num_ctx=%d; "
            "Ollama will truncate it and the model will not see the whole context",
            model,
            tokens,
            _NUM_CTX,
        )


def _gen_options(num_predict: int | None) -> dict[str, Any]:
    options: dict[str, Any] = {"temperature": 0, "num_ctx": _NUM_CTX}
    if num_predict is not None:
        options["num_predict"] = num_predict
    return options


def generate_json(
    prompt: str,
    *,
    model: str | None = None,
    keep_alive: str | None = None,
    num_predict: int | None = None,
) -> dict[str, Any]:
    """One prompt → parsed JSON dict. Raises on HTTP or JSON failure."""
    _warn_if_oversized(prompt, model or settings.brain_model)
    response = httpx.post(
        f"{settings.ollama_url}/api/generate",
        json={
            "model": model or settings.brain_model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "think": False,
            "keep_alive": keep_alive or settings.brain_keep_alive,
            "options": _gen_options(num_predict),
        },
        timeout=_TIMEOUT_S,
    )
    response.raise_for_status()
    return json.loads(response.json()["response"])


def generate_text_stream(
    prompt: str,
    *,
    model: str | None = None,
    keep_alive: str | None = None,
    num_predict: int | None = None,
) -> Iterator[str]:
    """Yield Ollama response text chunks for a plain-text answer prompt."""
    _warn_if_oversized(prompt, model or settings.brain_model)
    with httpx.stream(
        "POST",
        f"{settings.ollama_url}/api/generate",
        json={
            "model": model or settings.brain_model,
            "prompt": prompt,
            "stream": True,
            "think": False,
            "keep_alive": keep_alive or settings.brain_keep_alive,
            "options": _gen_options(num_predict),
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


def embed(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    """Batch of texts → one vector each, via one /api/embed call.

    Always keep_alive=0 — the embedder is tiny but the Pi never keeps an extra
    model resident. Raises on HTTP failure like the generate fns.
    """
    response = httpx.post(
        f"{settings.ollama_url}/api/embed",
        json={
            "model": model or settings.embed_model,
            "input": texts,
            "keep_alive": 0,
        },
        timeout=_TIMEOUT_S,
    )
    response.raise_for_status()
    return response.json()["embeddings"]


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
