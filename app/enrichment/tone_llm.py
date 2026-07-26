"""Asking the local model for a hard-news tone label (#639).

The rubric exists because the thing being measured is ambiguous, and the
ambiguity is the point of #639. VADER scores the *valence of the words*: "50
killed" is negative because "killed" is a negative word. `_tone_lean` reports
that as a bloc's **emotional lean**, which readers will take as a claim about
how that country's press framed the story.

Those come apart on exactly the corpus this system ingests. Every outlet
reporting a massacre writes negative words; that says nothing about whether one
of them framed it sympathetically and another dismissively. So the prompt asks
for the *reporting stance toward the subject*, and says so explicitly, rather
than assuming the model shares VADER's definition.

Two labels can therefore disagree without either being wrong — which is itself
a finding, and why #639 prints the disagreements rather than only a percentage.

Never on the ingest path, same rule as #591: this is a measurement, and a model
outage must cost a report, never an article.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

METHOD: str = "tone-llm-v1"

#: Small models wrap answers in chatter; failing on that would discard usable
#: labels. Same extraction the severity grader uses.
_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)

VALID_TONES: frozenset[str] = frozenset({"negative", "neutral", "positive"})

PROMPT = """You label the TONE of a news headline: how the outlet reports its subject.

This is about the REPORTING, not about whether the event is good or bad.
A tragedy reported plainly is neutral. A routine policy story written with
contempt is negative.

  negative  hostile, critical, alarmed, or condemning toward its subject
  neutral   plain factual reporting, however grim the facts are
  positive  approving, sympathetic, celebratory, or reassuring

Rules:
- Grim facts alone are NOT negative tone. "40 killed in earthquake" reported
  straight is neutral: the event is terrible, the reporting is flat.
- Judge the wording, not the event. "Regime slaughters civilians" and
  "Government forces engage militants" describe one event in two tones.
- Loaded nouns, scare quotes and sneering qualifiers make it negative.
- If nothing marks the wording either way, answer neutral. Neutral is the
  correct answer for most straight reporting, not a way of giving up.
- Judge only this headline. Do not infer the outlet's politics.

Answer with JSON only:
{{"tone": "negative"|"neutral"|"positive", "reason": "<one short sentence>"}}

Headline: {headline}
"""


def build_prompt(headline: str, summary: str = "") -> str:
    text = f"{headline} {summary}".strip() if summary else headline
    return PROMPT.format(headline=text)


def tone_from_payload(payload: Any) -> str | None:
    """Parsed model JSON → a tone label, or None when it is unusable.

    None rather than a raise: one bad answer should skip a headline, not end a
    measurement run, and #639 counts the unscored rows rather than hiding them.
    """
    if not isinstance(payload, dict):
        return None
    tone = payload.get("tone")
    if not isinstance(tone, str):
        return None
    cleaned = tone.strip().lower()
    if cleaned not in VALID_TONES:
        logger.warning("tone label outside the rubric: %r", tone)
        return None
    return cleaned


def parse_response(body: str) -> str | None:
    """Raw model text → a tone label. Extracts the JSON first."""
    match = _JSON_RE.search(body or "")
    if match is None:
        return None
    try:
        payload: Any = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return tone_from_payload(payload)
