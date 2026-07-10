"""Claim extraction — prompt + mechanical validation (WS-G step 1, #378).

The prompt and the validation are declared here and versioned; changing
either is a new PROMPT_VERSION / METHOD_VERSION, never a silent edit. The
model's raw output is *validated mechanically* (ISO2 shape, enum membership,
non-negative integer) but never corrected — a wrong-but-well-formed claim is
stored as-is, because measuring that wrongness is the whole point.
"""

from __future__ import annotations

from typing import Any

OLLAMA_MODEL_DEFAULT: str = "qwen3.5:4b-q4_K_M"
PROMPT_VERSION: str = "p1"
METHOD_VERSION: str = f"claims-{OLLAMA_MODEL_DEFAULT.replace(':', '-')}-{PROMPT_VERSION}"

#: The four WS-C claim types plus the honest default.
EVENT_TYPES: frozenset[str] = frozenset(
    ["earthquake", "wildfire", "disaster", "market_crash", "none"]
)

_PROMPT_TEMPLATE = """You extract factual claims from news headlines about one real-world story.

Headlines (same story, different outlets):
{titles}

Respond with ONLY a JSON object with exactly these keys:
- "countries": list of ISO 3166-1 alpha-2 codes of countries the story is about (e.g. ["TR"])
- "event_type": exactly one of "earthquake", "wildfire", "disaster", "market_crash", "none"
- "casualties": the number of deaths claimed, as an integer, or null if none stated

JSON:"""


def build_prompt(titles: list[str]) -> str:
    listed = "\n".join(f"- {title}" for title in titles if title)
    return _PROMPT_TEMPLATE.format(titles=listed)


def parse_claims(raw: Any) -> dict[str, Any]:
    """Mechanically validate the model's JSON. Invalid parts degrade, never guess."""
    if not isinstance(raw, dict):
        raw = {}

    countries = [
        c.upper()
        for c in raw.get("countries") or []
        if isinstance(c, str) and len(c) == 2 and c.isalpha()
    ]

    event_type = raw.get("event_type")
    if event_type not in EVENT_TYPES:
        event_type = "none"

    casualties = raw.get("casualties")
    if not isinstance(casualties, int) or isinstance(casualties, bool) or casualties < 0:
        casualties = None

    return {"countries": countries, "event_type": event_type, "casualties": casualties}
