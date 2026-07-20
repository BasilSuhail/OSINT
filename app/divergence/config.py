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

_PHYSICAL: Final[frozenset[str]] = frozenset(
    {
        "nasa-firms",
        "usgs-quake",
        "gdacs",
        "eonet",
        "opensky-adsb",
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
    if slug in _PHYSICAL:
        return "physical"
    if slug == "gdelt" or slug.startswith("rss-"):
        return "narrative"
    return None
