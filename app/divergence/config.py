"""Frozen divergence parameters + source-side classification."""

from __future__ import annotations

from typing import Final, Literal

#: Bumped together with any change to weights/thresholds. Never edited in place.
#:
#: v2 (#526): z-scores require a full ROLLING_WINDOW_DAYS baseline. v1 scored
#: from as few as two prior points, whose near-zero standard deviation made
#: ordinary days read as 3-5 sigma — phantom spikes that dominated the
#: lead-time gate's result.
#: v3 (#528): the physical side became the day's strongest event on the
#: magnitude scale rather than a count of rows, and the narrative side became
#: coverage of the event rather than a country's entire news output. Both sides
#: were previously too blunt to see the thing being measured.
#: v4 (#544): detect_lead searches both sides of the narrative spike. Searching
#: only backward meant a positive lead was the only possible result, so the
#: measurement could not distinguish a real effect from the detector's own bias.
#:
#: Deliberately NOT bumped for #497. Excluding nasa-firms and opensky-adsb from
#: the physical side is a no-op on every number: both scored 0.0 and 0.0 never
#: beat the 0.0 default, so no series, spike or lead changes. Bumping would
#: invalidate comparable results to advertise a change that did not happen.
DIVERGENCE_METHOD_VERSION: Final[str] = "div.v4"

#: Trailing window for the rolling z-score baseline, in days.
ROLLING_WINDOW_DAYS: Final[int] = 28

#: z-score thresholds a side must cross to count as a "spike".
TAU_P: Final[float] = 1.5
TAU_N: Final[float] = 1.5

#: log1p ceilings (the count that reads as "fully saturated") per side.
#: The physical side is now a magnitude (#528), so the ceiling is a magnitude:
#: 200 was chosen when the value was a count of events per day.
LOG_CEILING_PHYSICAL: Final[float] = 10.0
LOG_CEILING_NARRATIVE: Final[float] = 300.0

#: How far before a narrative spike we look for a physical spike, in days.
MAX_LEAD_LOOKBACK_DAYS: Final[int] = 21

#: Physical sources that cannot express an intensity, and so are excluded from
#: divergence scoring entirely (#497).
#:
#: The physical side is a magnitude axis: `daily_physical_intensity` takes the
#: day's strongest event, using `severity * 10` for events without a magnitude.
#: A source with no severity and no magnitude scores 0.0, which never beats the
#: 0.0 default — so it is silently indistinguishable from a day on which
#: nothing happened.
#:
#: Measured on 2026-07-21: nasa-firms had severity NULL on all 536,097 rows and
#: opensky-adsb hard-codes severity 0.0 across 58,226. Together that is 594,323
#: of 595,353 physical-side rows — 99.8% — contributing nothing while appearing
#: to be sensors. Excluding them changes no number; it stops the codebase
#: claiming a measurement it never made.
#:
#: These are real signals and belong in the analysis eventually. Folding them
#: in means giving them an intensity of their own — aircraft counts and fire
#: pixels are not magnitudes, and `max()` over a shared axis is the wrong shape
#: for them. That is a modelling decision, not a classification fix.
INTENSITY_BLIND_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "nasa-firms",
        "opensky-adsb",
    }
)

_PHYSICAL: Final[frozenset[str]] = frozenset(
    {
        "usgs-quake",
        "gdacs",
        "eonet",
        "viirs-flaring",
        "aisstream",
    }
)


def classify_side(source: str) -> Literal["physical", "narrative"] | None:
    """Return which divergence side a source slug belongs to.

    Returns:
        "physical" if source is in the physical set, "narrative" for narrative
        sources, or None if the source is excluded from divergence scoring.
    """
    slug = (source or "").lower()
    if slug in INTENSITY_BLIND_SOURCES:
        return None
    if slug in _PHYSICAL:
        return "physical"
    if slug == "gdelt" or slug.startswith("rss-"):
        return "narrative"
    return None
