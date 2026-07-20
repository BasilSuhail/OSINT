"""Numeral grounding for story gists (#514).

The 1.5b model was observed turning "at least one dead" into "at least five
deaths". A gist is what the Q&A model quotes, so an invented casualty figure
reaches the user as reported fact. This module answers one question: does every
figure in a gist appear in the headlines the gist was built from?

Both sides are normalised to plain numbers, so "five" in a gist is grounded by
"5" in a headline. Grounding is exact — there is no tolerance band and no
exemption for ages, years or magnitudes. A figure the sources do not carry is
invention regardless of what it counts.
"""

from __future__ import annotations

import re

#: Written cardinals the model realistically emits. Ordinals are deliberately
#: absent: "the third strike" is a rank, not a figure to ground.
_WORD_VALUES: dict[str, float] = {
    "zero": 0.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "eleven": 11.0,
    "twelve": 12.0,
    "thirteen": 13.0,
    "fourteen": 14.0,
    "fifteen": 15.0,
    "sixteen": 16.0,
    "seventeen": 17.0,
    "eighteen": 18.0,
    "nineteen": 19.0,
    "twenty": 20.0,
    "thirty": 30.0,
    "forty": 40.0,
    "fifty": 50.0,
    "sixty": 60.0,
    "seventy": 70.0,
    "eighty": 80.0,
    "ninety": 90.0,
}

_SCALES: dict[str, float] = {
    "hundred": 100.0,
    "thousand": 1_000.0,
    "million": 1_000_000.0,
    "billion": 1_000_000_000.0,
}

#: A digit group (thousands separators and one decimal part allowed) or a word.
#: Hyphens are separators, so "twenty-five" reads as one run and "18-month"
#: yields the 18 without dragging the unit in.
_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?|[a-z]+")


def _digits_to_float(token: str) -> float | None:
    cleaned = token.strip(",").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _run_value(run: list[tuple[str, float]]) -> float:
    """Fold consecutive numeric tokens into one figure.

    "twenty" "five" -> 25; "1.5" "million" -> 1_500_000; "three" "thousand"
    -> 3_000. A bare scale word with nothing in front of it counts as one of
    itself, which is how "thousand-strong" reads.
    """
    total = 0.0
    current = 0.0
    for kind, value in run:
        if kind == "value":
            current += value
        elif value == 100.0:
            current = (current or 1.0) * value
        else:
            total += (current or 1.0) * value
            current = 0.0
    return total + current


def extract_numerals(text: str) -> set[float]:
    """Every figure in `text`, as plain numbers.

    Digit forms and written forms normalise to the same value so the two can be
    compared across a gist and its headlines.
    """
    if not text:
        return set()

    found: set[float] = set()
    run: list[tuple[str, float]] = []

    def flush() -> None:
        if run:
            found.add(_run_value(run))
            run.clear()

    for token in _TOKEN.findall(text.lower()):
        if token[0].isdigit():
            value = _digits_to_float(token)
            if value is None:
                flush()
                continue
            run.append(("value", value))
        elif token in _WORD_VALUES:
            run.append(("value", _WORD_VALUES[token]))
        elif token in _SCALES:
            run.append(("scale", _SCALES[token]))
        else:
            flush()
    flush()
    return found


def format_figure(value: float) -> str:
    """A figure as a human would write it — 5 not 5.0, 5.1 kept."""
    return str(int(value)) if value.is_integer() else str(value)


def unsupported_numerals(gist: str, titles: list[str]) -> list[float]:
    """Figures the gist asserts that none of its headlines carry.

    Empty means the gist is grounded. Anything returned was invented during
    enrichment and the gist must not be stored as written.
    """
    grounded: set[float] = set()
    for title in titles:
        grounded |= extract_numerals(title)
    return sorted(extract_numerals(gist) - grounded)
