"""Story review — contradiction detection + cluster QA in one call (WS-G step 3, #386).

One nightly prompt per multi-member story answers both remaining annotator
jobs from the #282 plan: *is this one real-world story?* (continuous audit of
the WS-A clustering threshold) and *do the outlets assert incompatible
facts?* (the facts-vs-framing typing WS-B may consume later — after this
annotator's own agreement is measured). Same guardrails as claim extraction:
declared prompt, versioned method, mechanical validation that degrades but
never guesses, consumed by nothing.
"""

from __future__ import annotations

from typing import Any

from app.validator.claims import OLLAMA_MODEL_DEFAULT

REVIEW_PROMPT_VERSION: str = "r1"
REVIEW_METHOD_VERSION: str = (
    f"review-{OLLAMA_MODEL_DEFAULT.replace(':', '-')}-{REVIEW_PROMPT_VERSION}"
)

KINDS: frozenset[str] = frozenset(["facts", "framing", "none"])

_PROMPT_TEMPLATE = """These news headlines were automatically grouped as ONE real-world story:
{titles}

Respond with ONLY a JSON object with exactly these keys:
- "one_story": true if all headlines describe the same real-world story, else false
- "contradiction": true if any two headlines assert incompatible facts \
(different death tolls, opposite outcomes), else false
- "kind": "facts" if the disagreement is about facts, "framing" if only \
tone/angle differs, "none" if there is no disagreement
- "note": one short sentence of evidence, or null

JSON:"""


def build_review_prompt(titles: list[str]) -> str:
    listed = "\n".join(f"- {title}" for title in titles if title)
    return _PROMPT_TEMPLATE.format(titles=listed)


def parse_review(raw: Any) -> dict[str, Any]:
    """Mechanically validate. Invalid parts degrade to unknown, never guess."""
    if not isinstance(raw, dict):
        raw = {}

    one_story = raw.get("one_story")
    if not isinstance(one_story, bool):
        one_story = None

    contradiction = raw.get("contradiction")
    if not isinstance(contradiction, bool):
        contradiction = None

    kind = raw.get("kind")
    if kind not in KINDS:
        kind = "none"
    if kind == "facts" and contradiction is not True:
        kind = "none"  # a factual contradiction type requires the contradiction

    note = raw.get("note")
    if not isinstance(note, str) or not note.strip():
        note = None

    return {"one_story": one_story, "contradiction": contradiction, "kind": kind, "note": note}
