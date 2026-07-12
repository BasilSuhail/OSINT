"""Verdict-vocabulary parity tests (#405).

The briefing's Python verdicts must read *word-identical* to the dashboard's
`osint-frontend/lib/verdicts.ts`. Two guarantees are pinned here:

1. Behaviour parity — the same inputs the frontend's vitest suite uses produce
   the same phrasings (mirrors ``__tests__/verdicts.test.ts``).
2. No drift — every canonical phrase the Python layer emits is asserted to be
   present *verbatim* in the TypeScript source file, so a wording change on
   either side that isn't mirrored on the other fails this test.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.briefing.verdicts import (
    contested_verdict,
    scoreboard_verdict,
    story_verdict,
)

_RAW_TS = (
    Path(__file__).resolve().parents[1] / "osint-frontend" / "lib" / "verdicts.ts"
).read_text()

# The TypeScript splits long sentences across adjacent string literals
# (``"…earned, " + "and…"``) and interpolates numbers (``${owners}``). Rejoin
# concatenations and drop interpolations so each sentence is contiguous text,
# matching the number-stripped phrase fragments the Python layer emits.
TS_SOURCE = re.sub(r"\$\{[^}]*\}", "", re.sub(r"[\"`]\s*\+\s*[\"`]", "", _RAW_TS))

# Canonical phrase fragments — number placeholders stripped so they match the
# template literals in verdicts.ts verbatim.
PHRASES = [
    "independent organisations and a physical sensor agree.",
    "Strongly corroborated — ",
    " independent organisations tell this story.",
    "Probably real — ",
    "A second organisation confirms this — worth a look, not yet solid.",
    "Only one organisation has said this — treat it as a rumour until someone else confirms.",
    " are telling this story ",
    "contested narratives are worth watching; they sometimes precede contested situations.",
    "No forecasts graded yet — the track record is still being earned, "
    "and it can never be backfilled.",
    "indistinguishable from guessing — published because honesty is the product.",
    "measurably better than guessing (0.250 is a coin flip).",
    "very differently",
    "somewhat differently",
]


def test_no_drift_every_phrase_lives_in_the_frontend_source() -> None:
    for phrase in PHRASES:
        assert phrase in TS_SOURCE, f"phrase drifted from verdicts.ts: {phrase!r}"


# --- storyVerdict parity (mirrors __tests__/verdicts.test.ts) ---


def test_sensor_backed_multi_owner_reads_as_verified() -> None:
    v = story_verdict({"owner_count": 13, "corroboration": 0.99, "confirmed": ["earthquake"]})
    assert (
        v == "As close to verified as news gets: 13 independent organisations "
        "and a physical sensor agree."
    )


def test_strong_unsensed_reads_as_strongly_corroborated() -> None:
    v = story_verdict({"owner_count": 4, "corroboration": 0.875, "confirmed": []})
    assert v == "Strongly corroborated — 4 independent organisations tell this story."


def test_two_owner_reads_as_probably_real() -> None:
    v = story_verdict({"owner_count": 2, "corroboration": 0.5, "confirmed": []})
    assert v == "Probably real — 2 independent organisations tell this story."


def test_weak_reads_as_worth_a_look() -> None:
    v = story_verdict({"owner_count": 1, "corroboration": 0.3, "confirmed": []})
    assert v == "A second organisation confirms this — worth a look, not yet solid."


def test_single_source_reads_as_rumour() -> None:
    v = story_verdict({"owner_count": 1, "corroboration": 0, "confirmed": []})
    assert v == (
        "Only one organisation has said this — treat it as a rumour until someone else confirms."
    )


def test_null_corroboration_is_treated_as_zero() -> None:
    v = story_verdict({"owner_count": 1, "corroboration": None, "confirmed": []})
    assert v.startswith("Only one organisation has said this")


# --- contestedVerdict parity ---


def test_contested_names_two_biggest_blocs_and_flags_strong_divergence() -> None:
    v = contested_verdict({"divergence": 0.885, "groups": {"GB": 4, "RU": 4, "FR": 1}})
    assert v == (
        "United Kingdom and Russia are telling this story very differently — "
        "contested narratives are worth watching; they sometimes precede "
        "contested situations."
    )


def test_contested_moderate_divergence_softens_wording() -> None:
    v = contested_verdict({"divergence": 0.4, "groups": {"GB": 1, "JP": 1}})
    assert "somewhat differently" in v


# --- scoreboardVerdict parity ---


def test_scoreboard_no_grades_reads_as_record_being_earned() -> None:
    v = scoreboard_verdict(0, None)
    assert v == (
        "No forecasts graded yet — the track record is still being earned, "
        "and it can never be backfilled."
    )


def test_scoreboard_coinflip_brier_says_so_plainly() -> None:
    v = scoreboard_verdict(120, 0.25)
    assert v == (
        "Across 120 graded forecasts the instruments are currently "
        "indistinguishable from guessing — published because honesty is the product."
    )


def test_scoreboard_winning_brier_stated_with_number() -> None:
    v = scoreboard_verdict(120, 0.12)
    assert v == (
        "Across 120 graded forecasts the record stands at Brier 0.120 — "
        "measurably better than guessing (0.250 is a coin flip)."
    )
