"""Guardrail test for the frozen gate registry payload.

The hash changed in #518, when the registry stopped being a single
placeholder ("frozen starter event for backtest smoke run") and became 22 real
M6.0+ anchors, and again in #528 when each anchor gained a topic so the
narrative query could be scoped to the event. Changing it must stay a
deliberate, reviewed act: a sample that
can drift silently is a sample that can be tuned until the gate passes.
"""

from app.backtest.registry import verify_frozen

FROZEN_HASH = "f74fb156ee66dbfe4a67aa399e857dba7a9f80d7f2d72dafcda7810e17201794"


def test_registry_is_frozen() -> None:
    verify_frozen("app/backtest/events.yaml", FROZEN_HASH)
