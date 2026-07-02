"""Tests for ``app.backtest.registry`` frozen registry helpers."""

from __future__ import annotations

import textwrap

import pytest

from app.backtest.registry import RegistryEditedError, load_registry, verify_frozen


def _write(tmp_path, body, frozen_hash=None):
    p = tmp_path / "events.yaml"
    header = f"frozen_hash: {frozen_hash}\n" if frozen_hash else ""
    p.write_text(header + textwrap.dedent(body))
    return p


_BODY = """
    events:
      - id: jp-quake-2024
        country: JP
        date: 2024-01-01
        domain: hazard
        source_url: https://example.org/jp
        notes: test event
"""


def test_load_registry_parses_events(tmp_path):
    events, content_hash = load_registry(_write(tmp_path, _BODY))
    assert len(events) == 1
    assert events[0].country == "JP"
    assert len(content_hash) == 64


def test_verify_frozen_passes_when_hash_matches(tmp_path):
    p = _write(tmp_path, _BODY)
    _, content_hash = load_registry(p)
    verify_frozen(p, content_hash)


def test_verify_frozen_raises_when_edited(tmp_path):
    p = _write(tmp_path, _BODY)
    _, original = load_registry(p)
    edited = _write(tmp_path, _BODY.replace("country: JP", "country: US"))
    with pytest.raises(RegistryEditedError):
        verify_frozen(edited, original)
