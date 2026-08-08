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
    #: Fraction of rows that must carry a country before the coverage check
    #: complains. Defaults to the strict shared threshold. A source lowers it
    #: only when some of its rows legitimately have no country — and says so,
    #: with the measurement, in the note (#827).
    severity_coverage_floor: float | None = None
    #: Fraction of rows that must carry a country before the coverage check
    #: complains. Defaults to the strict shared threshold. A source lowers it
    #: only when some of its rows legitimately have no country — and says so,
    #: with the measurement, in the note (#827).
    country_coverage_floor: float | None = None
    #: Why, when the declaration is surprising.
    note: str = ""


#: RSS feeds all run the same enrichment path, so they share one declaration.
RSS_FAMILY = Expectation(
    severity="continuous",
    country="required",
    feeds_composite=False,
    note=(
        "Sentiment-derived, so nominally continuous. Measured live it takes "
        "exactly two values, 0.35 and 0.65, across all 19,722 rows — the audit "
        "should say so rather than the table being edited to match. Country is "
        "required because the map uses it for news navigation (#717). Resolver "
        "ambiguity can still leave honest nulls; those shortfalls must remain "
        "visible findings instead of being muted as optional."
    ),
    #: Measured over seven days across the 41 news feeds carrying at least
    #: thirty rows: min 0.375, p10 0.601, median 0.764, max 1.000. The strict
    #: 0.99 default fired on 45 of them nightly, because #717 established that
    #: roughly 41% of news is honestly countryless and must stay null. The bar
    #: sits between the worst feed and the tenth percentile: below it a feed is
    #: out of family with its peers, which is a defect worth a name (#827).
    country_coverage_floor=0.50,
)

EXPECTATIONS: dict[str, Expectation] = {
    "yfinance": Expectation(
        severity="continuous",
        country="required",
        feeds_composite=True,
        note="Drawdown against a rolling 30d max, saturating at 30%.",
    ),
    "fred": Expectation(
        severity="continuous",
        country="required",
        feeds_composite=True,
        severity_coverage_floor=0.70,
        note=(
            "Severity is computed in the fetcher from each series' own recent "
            "history (#684), and the panel covers 27 countries since #691 — 874 "
            "rows, 576 distinct severities, no value holding more than 7%. The "
            "floor is lowered because a quarter of the rows legitimately carry "
            "none: _series_to_events emits None until a series has MIN_HISTORY + 1 "
            "observations to judge against, and the fetcher re-reads a rolling "
            "365-day window, so the first few points of each of the 54 series are "
            "always unscored. Measured 635 of 874 (#715)."
        ),
    ),
    "polymarket": Expectation(
        severity="continuous",
        country="none",
        feeds_composite=False,
        note=(
            "Prediction markets are global, so country none is defensible. It no "
            "longer claims to feed the composite (#682): severity here is market "
            "uncertainty, and of the 115 stored rows 94 were US 2028 primary "
            "horse-race markets and 9 were World Cup football, with exactly one "
            "about conflict. A 50/50 nomination race would have scored as maximum "
            "national stress. Category is PREDICTION now, outside the composite's "
            "vocabulary, so composite_reachability no longer applies."
        ),
    ),
    "gdelt": Expectation(
        severity="continuous",
        country="required",
        feeds_composite=True,
        #: Measured 26,380 of 29,497 rows over seven days — 0.894. The coder
        #: leaves a country off when its own geocoder found none, which is the
        #: honest answer; a bar above that reports it broken every night for
        #: working as designed (#827).
        country_coverage_floor=0.80,
        note="Goldstein/tone.",
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
