"""Grading news severity from the text, on the harm scale (#591).

Replaces a substring match. The old rule returned 0.65 if a headline contained
any of fifteen words and 0.35 otherwise, so "Workers strike over pay" and
"50 killed in market bombing" scored identically, and "crash" matched a car, a
share index and an aircraft alike. That single function produced 42 of the 50
findings in #580.

The model is another fallible annotator, never a judge (#378/#386). Every guard
here exists because something already went wrong: #514/#553 swept 138 stored
gists that cited figures their sources never contained.

Grading runs as a batch pass, never on the ingest path, so a model outage cannot
stall ingestion — `keyword_verdict` is what fetchers use at write time.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.brain import numerals
from app.severity import scale

logger = logging.getLogger(__name__)

METHOD: str = "news-llm-v1"
FALLBACK_METHOD: str = "news-keyword-v2"

#: Extracts the first JSON object from a response. Small models wrap their
#: answer in chatter; failing on that would discard usable verdicts.
_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)

#: Numbers that appear in the prompt itself — band edges and the casualty
#: thresholds. A rationale echoing these is quoting instructions, not inventing.
_RUBRIC_NUMERALS: frozenset[float] = frozenset(
    {0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 9.0, 10.0}
    | {band.lower for band in scale.BANDS}
    | {band.upper for band in scale.BANDS}
)

PROMPT = """You grade how severe a news headline is, on a scale of harm to people.

Bands — these are FLOORS, not ceilings:
  0.00-0.20  routine: policy, business, sport. Nothing happened to anyone.
  0.20-0.40  tension: protest, strike, diplomatic rupture. No violence.
  0.40-0.60  violence without confirmed death, or mass displacement.
  0.60-0.80  confirmed deaths (1-9), or a serious armed attack.
  0.80-1.00  10+ dead, massacre, atrocity, or mass-fatality disaster.

Rules:
- If anyone is confirmed killed, the score is AT LEAST 0.60. Never lower.
- If 10 or more are killed, the score is AT LEAST 0.80.
- Say plainly what happened. Write "killed", not "incident". Write "attack",
  not "situation". Do not soften it.
- Only cite numbers that appear in the headline. Never invent a death toll.
- Describe ONLY what happened. Do not mention this scale, its bands, its
  thresholds, or the score you chose. "Three killed in a bombing" — not
  "three deaths exceed the 0.60 threshold".
- Judge the actual event, not the wording. A "market crash" is financial, not
  violent. A "strike" may be industrial action, not an attack.

Answer with JSON only:
{{"severity": <number 0-1>, "rationale": "<one short blunt sentence>"}}

Headline: {headline}
"""


def build_prompt(headline: str, summary: str = "") -> str:
    text = f"{headline} {summary}".strip() if summary else headline
    return PROMPT.format(headline=text)


def parse_response(body: str, *, headline: str) -> scale.Verdict | None:
    """Raw model text → a Verdict. Extracts the JSON, then applies every guard.

    Kept for responses that are not already parsed; `verdict_from_payload` is
    the path used when Ollama is asked with `format: json`.
    """
    match = _JSON_RE.search(body or "")
    if match is None:
        return None
    try:
        payload: Any = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return verdict_from_payload(payload, headline=headline)


def verdict_from_payload(payload: Any, *, headline: str) -> scale.Verdict | None:
    """Parsed model JSON → a Verdict, or None when any guard rejects it.

    Returning None rather than raising: one bad answer should skip a row, not
    fail a batch. The caller keeps whatever the fallback already stored.
    """
    if not isinstance(payload, dict):
        return None

    raw_value = payload.get("severity")
    rationale = payload.get("rationale")
    if raw_value is None or not isinstance(rationale, str) or not rationale.strip():
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    if not 0.0 <= value <= 1.0:
        return None

    # #514's guard: a figure in the rationale must appear in the source text.
    # The scale's own constants are exempt — a model that quotes the rubric
    # ("47 deaths exceed the 10-death threshold, minimum 0.80") is citing this
    # prompt, not inventing a casualty figure, and rejecting that discarded a
    # correct verdict in live testing.
    invented = [
        value
        for value in numerals.unsupported_numerals(rationale, [headline])
        if value not in _RUBRIC_NUMERALS
    ]
    if invented:
        logger.warning(
            "severity rationale cites figures the headline lacks (%s): %r", invented, rationale
        )
        return None

    softened = scale.euphemism_in(rationale, value=value)
    if softened is not None:
        logger.warning("severity rationale softens a lethal event (%r): %r", softened, rationale)
        return None

    return scale.Verdict(value=value, rationale=rationale.strip(), method=METHOD)


#: Words that indicate someone died. Distinct from "violent but not fatal" so
#: the fallback can respect the lethal floor instead of collapsing everything
#: into one value.
_LETHAL_WORDS: tuple[str, ...] = (
    "killed",
    "dead",
    "deaths",
    "fatal",
    "massacre",
    "died",
    "slain",
)

_VIOLENT_WORDS: tuple[str, ...] = (
    "attack",
    "explosion",
    "bombing",
    "shooting",
    "stabbed",
    "wounded",
    "injured",
    "gunmen",
    "airstrike",
    "war",
)

_DISRUPTION_WORDS: tuple[str, ...] = (
    "protest",
    "strike",
    "evacuated",
    "earthquake",
    "flood",
    "wildfire",
    "riot",
    "sanctions",
)


def keyword_verdict(title: str, summary: str) -> scale.Verdict:
    """Fast, deterministic fallback used on the ingest path.

    Still a keyword rule, but a graded one: it separates fatal from violent from
    disruptive rather than flattening all three onto 0.65. It always states its
    reason, so even the fallback is interrogable.
    """
    text = f"{title} {summary}".lower()

    for word in _LETHAL_WORDS:
        if word in text:
            return scale.Verdict(
                value=scale.LETHAL_FLOOR,
                rationale=f"headline reports death ({word!r}) — keyword rule, not yet graded",
                method=FALLBACK_METHOD,
            )
    for word in _VIOLENT_WORDS:
        if word in text:
            return scale.Verdict(
                value=0.50,
                rationale=f"headline reports violence ({word!r}) — keyword rule, not yet graded",
                method=FALLBACK_METHOD,
            )
    for word in _DISRUPTION_WORDS:
        if word in text:
            return scale.Verdict(
                value=0.30,
                rationale=f"headline reports disruption ({word!r}) — keyword rule, not yet graded",
                method=FALLBACK_METHOD,
            )
    return scale.Verdict(
        value=0.15,
        rationale="no harm indicator in the headline — keyword rule, not yet graded",
        method=FALLBACK_METHOD,
    )
