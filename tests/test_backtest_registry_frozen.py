"""Guardrail test for the frozen gate registry payload.

The hash changed once, in #518, when the registry stopped being a single
placeholder ("frozen starter event for backtest smoke run") and became 22 real
M6.0+ anchors. Changing it must stay a deliberate, reviewed act: a sample that
can drift silently is a sample that can be tuned until the gate passes.
"""

from app.backtest.registry import verify_frozen

FROZEN_HASH = "d78f59d15b547301093d488f93dbceb351a4940cbc71b6a7017fa9ca6e781d98"


def test_registry_is_frozen() -> None:
    verify_frozen("app/backtest/events.yaml", FROZEN_HASH)
