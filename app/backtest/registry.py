"""Frozen event registry loader + edit guard."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml


class RegistryEditedError(RuntimeError):
    """Raised when a frozen registry's content hash no longer matches."""


@dataclass(frozen=True)
class RegistryEvent:
    """Single backtest anchor row."""

    id: str
    country: str
    date: date
    domain: str
    source_url: str
    notes: str
    #: What outlets would call this event, used to scope the narrative query so
    #: it measures coverage of THIS event rather than a country's whole news
    #: output (#528). Optional so older registries still load.
    topic: str | None = None


def _serialize_events(events: list[dict[str, Any]]) -> str:
    """Deterministic JSON serialization for content hashing."""
    return json.dumps(events, sort_keys=True, separators=(",", ":"), default=str)


def _content_hash(events: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_serialize_events(events).encode("utf-8")).hexdigest()


def load_registry(path: str) -> tuple[list[RegistryEvent], str]:
    """Load a registry YAML and return canonicalized events + content hash.

    The hash includes only the `events` payload so metadata (like
    `frozen_hash`) never affects detection.
    """
    raw = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("registry file must contain a mapping")

    events_raw = raw.get("events", [])
    if not isinstance(events_raw, list):
        raise ValueError("registry events must be a list")

    content_hash = _content_hash(events_raw)
    events: list[RegistryEvent] = []
    for item in events_raw:
        if not isinstance(item, dict):
            continue
        events.append(
            RegistryEvent(
                id=str(item["id"]),
                country=str(item["country"]),
                date=date.fromisoformat(str(item["date"])),
                domain=str(item["domain"]),
                source_url=str(item["source_url"]),
                notes=str(item["notes"]),
                topic=str(item["topic"]) if item.get("topic") else None,
            )
        )
    return events, content_hash


def verify_frozen(path: str, expected_hash: str) -> None:
    """Assert that the registry body hash has not changed."""
    _, content_hash = load_registry(path)
    if content_hash != expected_hash:
        raise RegistryEditedError(
            f"registry hash mismatch: expected {expected_hash}, got {content_hash}"
        )
