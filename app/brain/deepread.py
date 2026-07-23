"""On-demand deep read of a contested story (#607).

The deterministic framing block (#605) says HOW the country blocs word a story
differently; this asks the local model to say WHY, in prose. It is generated
only when the reader taps for it — never precomputed — so the story card stays a
fast DB read. The prompt takes no side and is grounded strictly in the headlines
handed to it, so the deep read cannot invent a motive the coverage does not show.
"""

from __future__ import annotations

import json

#: Token cap for the deep read: a few paragraphs, no runaway generation on the Pi.
DEEP_READ_NUM_PREDICT: int = 512

#: Headlines per bloc fed to the model — enough to show the framing, capped so a
#: heavily-covered story cannot blow the context window.
_HEADLINES_PER_BLOC: int = 6


def deep_read_blocs(members: list[dict], framing: dict) -> list[dict]:
    """Attach each bloc's outlet+headline lines to its framing profile (#607).

    Ordered as the framing's blocs (loudest first); a bloc with no usable
    headline is dropped, and each bloc is capped at `_HEADLINES_PER_BLOC`.
    """
    profile = {b["country"]: b for b in framing["blocs"]}
    lines: dict[str, list[str]] = {}
    for m in members:
        country = m.get("origin_country") or "??"
        if country not in profile:
            continue
        headline = (m.get("title") or "").strip()
        if not headline:
            continue
        outlet = (m.get("outlet") or m.get("source") or "").strip()
        lines.setdefault(country, []).append(f"{outlet}: {headline}" if outlet else headline)
    out: list[dict] = []
    for b in framing["blocs"]:
        heads = lines.get(b["country"])
        if not heads:
            continue
        out.append(
            {
                "country": b["country"],
                "tone": b["tone"],
                "terms": b["terms"],
                "headlines": heads[:_HEADLINES_PER_BLOC],
            }
        )
    return out


def build_deep_read_prompt(title: str, blocs: list[dict]) -> str:
    """Prompt for the WHY behind a contested telling (#607).

    Neutral and grounded: the model explains how each country bloc frames the
    story and why they might differ, using only the headlines given, taking no
    side, and labelling any why-they-differ reasoning as its own read rather
    than reported fact.
    """
    return (
        "You are a neutral media analyst. Several countries' outlets are covering "
        "the SAME story but wording it differently. Explain, in plain "
        "conversational English, how each country bloc frames it and why they "
        "might differ.\n\n"
        "Rules:\n"
        "- Take NO side. Do not endorse any country's framing; describe them "
        "even-handedly.\n"
        "- Use ONLY the headlines provided below. Invent no facts, events, "
        "names, or numbers that are not in them.\n"
        "- Give each bloc its own short paragraph: what it emphasises and the "
        "tone it takes.\n"
        "- Then one short closing paragraph on WHY the framings likely differ. "
        "This part is your own reading, not reported fact — open it with "
        "'Why they differ (my read):' and use tentative words like 'likely' or "
        "'may'. Label it, do not state it as certain.\n"
        "- Plain flowing paragraphs only. No markdown, no bullet lists, no "
        "headers.\n\n"
        f"STORY: {title}\n\n"
        f"BLOCS (country code, tone lean, signature words, their headlines):\n"
        f"{json.dumps(blocs, ensure_ascii=False)}\n"
    )
