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
from functools import lru_cache
from typing import Any

from app.brain import numerals
from app.severity import scale

logger = logging.getLogger(__name__)

METHOD: str = "news-llm-v1"
BAND_METHOD: str = "news-llm-band-v1"
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


#: The same grading job, asking for the band's name instead of a number (#649).
#:
#: #646 benched five smaller models and found they classify correctly in prose
#: and then emit an unrelated float — `qwen2.5:1.5b` called a story "a routine
#: policy or business matter" and scored it 0.6, which is the confirmed-deaths
#: band. Naming what kind of event happened is the part a small model can do;
#: holding five numeric intervals in working memory and mapping onto the right
#: one is the part it cannot. So this asks only for the part it can do, and
#: `scale.value_for_band` does the mapping where it cannot be got wrong.
#:
#: The rules are #591's rules verbatim, minus the two that talk about numbers —
#: a model that never emits a value cannot be told to keep that value above a
#: floor, so the floors are stated as which band to choose instead.
BAND_PROMPT = """You grade how severe a news headline is, on a scale of harm to people.

Choose exactly one band:
  routine        policy, business, sport. Nothing happened to anyone.
  tension        protest, strike, diplomatic rupture. No violence.
  violence       violence without confirmed death, or mass displacement.
  grave          confirmed deaths (1-9), or a serious armed attack.
  mass_casualty  10+ dead, massacre, atrocity, or mass-fatality disaster.

Rules:
- If anyone is confirmed killed, the band is AT LEAST grave. Never lower.
- If 10 or more are killed, the band is mass_casualty.
- Say plainly what happened. Write "killed", not "incident". Write "attack",
  not "situation". Do not soften it.
- Only cite numbers that appear in the headline. Never invent a death toll.
- Describe ONLY what happened. Do not mention this scale, its bands, or the
  band you chose. "Three killed in a bombing" — not "this is the grave band".
- Judge the actual event, not the wording. A "market crash" is financial, not
  violent. A "strike" may be industrial action, not an attack.

Answer with JSON only:
{{"band": "<one of: routine, tension, violence, grave, mass_casualty>",
  "rationale": "<one short blunt sentence>"}}

Headline: {headline}
"""


def build_prompt(headline: str, summary: str = "") -> str:
    text = f"{headline} {summary}".strip() if summary else headline
    return PROMPT.format(headline=text)


def build_band_prompt(headline: str, summary: str = "") -> str:
    text = f"{headline} {summary}".strip() if summary else headline
    return BAND_PROMPT.format(headline=text)


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

    return _guarded(value, rationale, headline=headline, method=METHOD)


def band_verdict_from_payload(payload: Any, *, headline: str) -> scale.Verdict | None:
    """Parsed model JSON naming a band → a Verdict, or None (#649).

    Same guards as the numeric path, deliberately: the protocol changes what the
    model is asked for, not what the system is willing to store. An unknown band
    name is rejected rather than coerced to the nearest one — a model answering
    "severe" has not named a band, and guessing which one it meant would invent
    a judgement nobody made.
    """
    if not isinstance(payload, dict):
        return None

    raw_band = payload.get("band")
    rationale = payload.get("rationale")
    if not isinstance(raw_band, str) or not isinstance(rationale, str) or not rationale.strip():
        return None

    band = scale.band_by_name(raw_band)
    if band is None:
        logger.warning("severity verdict names no known band (%r)", raw_band)
        return None

    return _guarded(scale.value_for_band(band), rationale, headline=headline, method=BAND_METHOD)


def _guarded(value: float, rationale: str, *, headline: str, method: str) -> scale.Verdict | None:
    """The checks every verdict passes, whichever protocol produced it.

    Shared rather than duplicated per protocol: a guard that exists on one path
    and not the other is how #514 happens twice.
    """
    # #514's guard: a figure in the rationale must appear in the source text.
    # The scale's own constants are exempt — a model that quotes the rubric
    # ("47 deaths exceed the 10-death threshold, minimum 0.80") is citing this
    # prompt, not inventing a casualty figure, and rejecting that discarded a
    # correct verdict in live testing.
    invented = [
        figure
        for figure in numerals.unsupported_numerals(rationale, [headline])
        if figure not in _RUBRIC_NUMERALS
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

    return scale.Verdict(value=value, rationale=rationale.strip(), method=method)


#: Words that indicate someone died.
#:
#: Matched on word boundaries, never as substrings. A plain ``in`` test
#: read "dead" inside *deadline* and "war" inside *software*, *warning*
#: and *toward* — 875 stories in a week raised to violent or lethal by a
#: spelling coincidence, while "Israeli Forces Kill Three Palestinians"
#: sat at 0.15 because the list held only the past tense (#739).
#:
#: Harm is harm whoever caused it. These lists name what happened, never
#: who did it, so the same act scores the same from any source and in
#: either direction.
_LETHAL_WORDS: tuple[str, ...] = (
    "killed",
    "kill",
    "kills",
    "killing",
    "killings",
    "dead",
    "death",
    "deaths",
    "died",
    "dies",
    "dying",
    "fatal",
    "fatally",
    "fatality",
    "fatalities",
    "massacre",
    "massacred",
    "slain",
    "murder",
    "murders",
    "murdered",
    "assassinated",
    "assassination",
    "homicide",
    "manslaughter",
    "executed",
    "beheaded",
    "lynched",
)

_VIOLENT_WORDS: tuple[str, ...] = (
    "attack",
    "attacks",
    "attacked",
    "explosion",
    "explosions",
    "blast",
    "blasts",
    "bomb",
    "bombs",
    "bombing",
    "bombings",
    "bombed",
    "shooting",
    "shootings",
    "shot",
    "gunfire",
    "gunmen",
    "gunman",
    "stabbed",
    "stabbing",
    "rape",
    "raped",
    "rapes",
    "torture",
    "tortured",
    "terror",
    "terrorist",
    "terrorists",
    "terrorism",
    "kidnapped",
    "kidnapping",
    "abducted",
    "hostage",
    "hostages",
    "wounded",
    "injured",
    "airstrike",
    "airstrikes",
    "shelling",
    "war",
    "wars",
)

_DISRUPTION_WORDS: tuple[str, ...] = (
    "protest",
    "protests",
    "protesters",
    "strike",
    "strikes",
    "evacuated",
    "evacuation",
    "earthquake",
    "flood",
    "floods",
    "flooding",
    "wildfire",
    "wildfires",
    "riot",
    "riots",
    "sanctions",
    "curfew",
    "looting",
)


@lru_cache(maxsize=3)
def _pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    """One alternation over a word list, anchored on word boundaries.

    Built once per list. Longest first so the rationale names the fuller
    match — "bombing" rather than "bomb" — which is what a reader checking
    the score wants to see.
    """
    ordered = sorted(words, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in ordered) + r")\b")


def keyword_verdict(title: str, summary: str) -> scale.Verdict:
    """Fast, deterministic fallback used on the ingest path.

    Still a keyword rule, but a graded one: it separates fatal from violent from
    disruptive rather than flattening all three onto 0.65. It always states its
    reason, so even the fallback is interrogable.
    """
    text = f"{title} {summary}".lower()

    lethal = _pattern(_LETHAL_WORDS).search(text)
    if lethal:
        return scale.Verdict(
            value=scale.LETHAL_FLOOR,
            rationale=(
                f"headline reports death ({lethal.group(1)!r}) — keyword rule, not yet graded"
            ),
            method=FALLBACK_METHOD,
        )
    violent = _pattern(_VIOLENT_WORDS).search(text)
    if violent:
        return scale.Verdict(
            value=0.50,
            rationale=(
                f"headline reports violence ({violent.group(1)!r}) — keyword rule, not yet graded"
            ),
            method=FALLBACK_METHOD,
        )
    disruption = _pattern(_DISRUPTION_WORDS).search(text)
    if disruption:
        return scale.Verdict(
            value=0.30,
            rationale=(
                f"headline reports disruption ({disruption.group(1)!r})"
                " — keyword rule, not yet graded"
            ),
            method=FALLBACK_METHOD,
        )
    return scale.Verdict(
        value=0.15,
        rationale="no harm indicator in the headline — keyword rule, not yet graded",
        method=FALLBACK_METHOD,
    )
