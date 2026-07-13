"""The brain's story enrichment (#413) — a light gist + two enum tags per story.

Timely first-look from the 1.5b model on idle windows; complements the nightly
4b claim extraction. No-fabrication: the gist describes only the supplied
headlines. The tags are fixed enums so a small model stays reliable and the
values are filterable — anything off-enum is coerced to a safe fallback.
"""

from __future__ import annotations

import json
from typing import Any

CATEGORIES: frozenset[str] = frozenset({"conflict", "economy", "disaster", "politics", "other"})
ESCALATING: frozenset[str] = frozenset({"yes", "no", "unclear"})

METHOD_VERSION: str = "enrich-v1.0"
PROMPT_VERSION: str = "enrich-prompt-v1.0"
GIST_MAX_CHARS: int = 240

#: How many member headlines the prompt carries — enough signal, bounded tokens.
MAX_TITLES: int = 5


def build_gist_prompt(titles: list[str]) -> str:
    headlines = "\n".join(f"- {t}" for t in titles if t)
    return (
        "You summarize a news story for an OSINT dashboard. Below are the "
        "headlines of the outlets telling one story. Using ONLY these headlines "
        "(invent nothing), return a JSON object with exactly these keys:\n"
        '  "gist": one short plain-English sentence, what this story is.\n'
        '  "category": one of conflict, economy, disaster, politics, other.\n'
        '  "escalating": one of yes, no, unclear — is the situation intensifying?\n\n'
        f"HEADLINES:\n{headlines}"
    )


def parse_gist(raw: dict[str, Any]) -> dict[str, str]:
    gist = raw.get("gist")
    gist = gist.strip()[:GIST_MAX_CHARS] if isinstance(gist, str) else ""
    category = raw.get("category")
    category = category if isinstance(category, str) and category in CATEGORIES else "other"
    escalating = raw.get("escalating")
    escalating = (
        escalating if isinstance(escalating, str) and escalating in ESCALATING else "unclear"
    )
    return {"gist": gist, "category": category, "escalating": escalating}


def _pretty(payload: dict[str, str]) -> str:
    """Compact JSON — handy for `make enrich` output and debugging."""
    return json.dumps(payload, ensure_ascii=False)
