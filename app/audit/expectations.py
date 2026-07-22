"""What each source is supposed to produce (#580).

This table is the point of the audit. Every defect behind #576 §5 was a value
that looked fine at every layer except the one that used it, and none of them
could be caught by a rule reading the data alone — severity is a two or three
level categorical almost everywhere, so "flag low variance" fires on nearly
every source and says nothing.

Declaring the intent makes the mismatch visible. `graded` is a legitimate
answer: GDACS having three alert levels is plausibly correct. The audit does not
object to a coarse scale, it objects to a coarse scale nobody declared, and to a
source claiming `continuous` while emitting two values.

Entries marked UNVERIFIED are the author's reading of the fetcher, not a
decision anyone has confirmed. They are deliberately written down rather than
left blank, so that correcting them is an edit instead of an investigation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SeverityKind = Literal["continuous", "graded", "none"]
CountryKind = Literal["required", "optional", "none"]


@dataclass(frozen=True)
class Expectation:
    """What a source is declared to produce."""

    #: continuous — a real scale. graded — a small ordinal set, by design.
    #: none — this source has no notion of severity.
    severity: SeverityKind
    #: required — every row should carry a country. optional — geography is
    #: genuinely absent for some rows. none — the source has no country at all.
    country: CountryKind
    #: Whether the composite is supposed to read this source. False is not a
    #: judgement about worth — most sources legitimately sit outside it.
    feeds_composite: bool
    #: Why, when the declaration is surprising.
    note: str = ""


#: RSS feeds all run the same enrichment path, so they share one declaration.
RSS_FAMILY = Expectation(
    severity="continuous",
    country="optional",
    feeds_composite=False,
    note=(
        "Sentiment-derived, so nominally continuous. Measured live it takes "
        "exactly two values, 0.35 and 0.65, across all 19,722 rows — the audit "
        "should say so rather than the table being edited to match."
    ),
)

EXPECTATIONS: dict[str, Expectation] = {
    "yfinance": Expectation(
        severity="continuous",
        country="required",
        feeds_composite=True,
        note="Drawdown against a rolling 30d max, saturating at 30%.",
    ),
    "fred": Expectation(
        severity="none",
        country="required",
        feeds_composite=True,
        note=(
            "The fetcher sets severity None and its docstring says the composite "
            "normalises it. The composite contains no such code, so this declares "
            "the fetcher's actual behaviour and composite_reachability is left to "
            "fail — which is the true statement about today."
        ),
    ),
    "polymarket": Expectation(
        severity="continuous",
        country="none",
        feeds_composite=True,
        note=(
            "Prediction markets are global, so country none is defensible. The "
            "composite filters country IS NOT NULL, so all rows drop. Declared "
            "feeds_composite True on purpose: the reachability finding is real."
        ),
    ),
    "gdelt": Expectation(
        severity="continuous", country="required", feeds_composite=True, note="Goldstein/tone."
    ),
    "acled": Expectation(
        severity="continuous", country="required", feeds_composite=True, note="UNVERIFIED"
    ),
    "emdat": Expectation(
        severity="continuous", country="required", feeds_composite=True, note="UNVERIFIED"
    ),
    "usgs-quake": Expectation(
        severity="continuous",
        country="optional",
        feeds_composite=True,
        note="Magnitude-derived. Offshore quakes have no country.",
    ),
    "gdacs": Expectation(
        severity="graded",
        country="optional",
        feeds_composite=True,
        note="Green/orange/red alert levels — three by design.",
    ),
    "nasa-firms": Expectation(
        severity="graded",
        country="optional",
        feeds_composite=True,
        note=(
            "Three levels because VIIRS confidence is l/n/h. #579 argues this is "
            "the wrong quantity — confidence is detection quality, not intensity "
            "— but graded describes what it is today."
        ),
    ),
    "eonet": Expectation(
        severity="graded", country="optional", feeds_composite=True, note="UNVERIFIED"
    ),
    "uk-police": Expectation(
        severity="none", country="required", feeds_composite=False, note="UNVERIFIED"
    ),
    "opensky-adsb": Expectation(
        severity="none",
        country="optional",
        feeds_composite=False,
        note=(
            "58,793 rows all carry severity 0.0. Declared none because a flight "
            "position has no severity; the constant is the defect, and the "
            "severity_constant check reports it regardless of declaration."
        ),
    ),
    "abuse-ch-urlhaus": Expectation(
        severity="graded", country="none", feeds_composite=False, note="UNVERIFIED"
    ),
    "abuse-ch-feodo": Expectation(
        severity="graded", country="none", feeds_composite=False, note="UNVERIFIED"
    ),
}

#: Sources whose name starts with this share RSS_FAMILY.
RSS_PREFIX = "rss-"


def for_source(source: str) -> Expectation | None:
    """The declaration for `source`, or None if nothing declares it.

    None is a finding, not an error — a new fetcher must not be able to enter
    the system unnoticed.
    """
    if source.startswith(RSS_PREFIX):
        return RSS_FAMILY
    return EXPECTATIONS.get(source)
