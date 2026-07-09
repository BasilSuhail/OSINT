"""corroboration-v1.0 — the fixed per-story confidence formula (WS-C step 4, #363).

Declared before any score distribution was looked at, same pre-registration
discipline as the composite. The formula in one sentence:

    Each additional independent teller halves the remaining doubt;
    a physical-sensor confirmation halves it once more.

        doubt = 2^-(owner_count - 1 + sensor_flag)
        score = 1 - doubt

Choices fixed a priori:

- A single unverified teller earns 0.0 — one feed saying something is the
  baseline, not evidence.
- Sensor confirmation is a flag, not a ladder: machines corroborate *that*
  something physical happened; two matching sensor rows do not make the story
  twice as true.
- Unconfirmed claims do not subtract. Sensor coverage is biased (no tornado
  feed, days-long FIRMS retention); penalising under-sensed events would bake
  that bias into the score. They stay visible in the components instead.
- Never a bare verdict: the components ship with the score so an analyst can
  disagree with the weighting.
"""

from __future__ import annotations

from typing import Any

SCORE_VERSION: str = "corroboration-v1.0"


def corroboration_score(
    *, owner_count: int, confirmed: int, unconfirmed: int
) -> tuple[float, dict[str, Any]]:
    """Score in [0, 1) plus its full evidence trail."""
    sensor_flag = 1 if confirmed > 0 else 0
    doubt = 2.0 ** -(max(owner_count, 1) - 1 + sensor_flag)
    score = 1.0 - doubt
    components = {
        "owner_count": owner_count,
        "sensor_confirmed": bool(sensor_flag),
        "confirmed_claims": confirmed,
        "unconfirmed_claims": unconfirmed,
        "claims_checked": confirmed + unconfirmed,
        "method_version": SCORE_VERSION,
    }
    return score, components
