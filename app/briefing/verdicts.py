"""Plain-English verdict layer — Python mirror of ``lib/verdicts.ts`` (#405).

Deterministic template sentences over measured numbers. No AI anywhere: every
phrase is a mechanical map from a number range to words, so the same number
always reads the same way in the dashboard and in the newsletter. The wording
here is pinned word-identical to the frontend by ``tests/test_verdicts.py`` —
change one side without the other and that test fails.
"""

from __future__ import annotations

from typing import Any

from app.enrichment.country_codes import iso2_to_name


def _country(code: str) -> str:
    return iso2_to_name(code) or code


def story_verdict(story: dict[str, Any]) -> str:
    score = story.get("corroboration") or 0
    owners = story["owner_count"]
    if score >= 0.75 and story["confirmed"]:
        return (
            f"As close to verified as news gets: {owners} independent organisations "
            "and a physical sensor agree."
        )
    if score >= 0.75:
        return f"Strongly corroborated — {owners} independent organisations tell this story."
    if score >= 0.5:
        return f"Probably real — {owners} independent organisations tell this story."
    if score > 0:
        return "A second organisation confirms this — worth a look, not yet solid."
    return "Only one organisation has said this — treat it as a rumour until someone else confirms."


def contested_verdict(item: dict[str, Any]) -> str:
    blocs = [
        _country(code) for code, _ in sorted(item["groups"].items(), key=lambda kv: -kv[1])[:2]
    ]
    pair = f"{blocs[0]} and {blocs[1]}" if len(blocs) == 2 else (blocs[0] if blocs else "Outlets")
    strength = "very differently" if item["divergence"] >= 0.7 else "somewhat differently"
    return (
        f"{pair} are telling this story {strength} — contested narratives are "
        "worth watching; they sometimes precede contested situations."
    )


def scoreboard_verdict(graded: int, brier: float | None) -> str:
    if graded == 0 or brier is None:
        return (
            "No forecasts graded yet — the track record is still being earned, "
            "and it can never be backfilled."
        )
    if brier >= 0.2:
        return (
            f"Across {graded} graded forecasts the instruments are currently "
            "indistinguishable from guessing — published because honesty is the product."
        )
    return (
        f"Across {graded} graded forecasts the record stands at Brier {brier:.3f} — "
        "measurably better than guessing (0.250 is a coin flip)."
    )
