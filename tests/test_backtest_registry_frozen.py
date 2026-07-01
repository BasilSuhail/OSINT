"""Guardrail test for the frozen gate registry payload."""

from app.backtest.registry import verify_frozen

FROZEN_HASH = "74607ce70c7c3569ead5463cdeff5d97f0972723c5fd17d37d5e878485c8c389"


def test_registry_is_frozen() -> None:
    verify_frozen("app/backtest/events.yaml", FROZEN_HASH)
