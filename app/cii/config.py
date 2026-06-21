"""Per-country baselines + event multipliers for CII v1.

The 12-country Tier-1 seed reflects what Basil's OSINT scope cares about
most. Countries outside the table fall back to ``DEFAULT_CII_BASELINE``
(baseline=15, multiplier=1.0). Numbers are editorial defaults — they get
revisited every methodology version bump.

Reference: koala73/worldmonitor ``docs/algorithms.mdx`` § "Country
Instability Index (CII)". WM tracks 31 Tier-1 countries; we ship 12 and
flag the remaining 19 as a follow-up.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CiiBaseline:
    """Structural-fragility prior + event sensitivity for one ISO."""

    #: Pre-configured baseline reflecting structural fragility (0-50 scale).
    baseline: float
    #: Multiplier applied to event aggregates before normalisation. >1 for
    #: more event-sensitive countries (active conflict zones); <1 for
    #: high-volume but low-stress feeds (US, UK).
    multiplier: float


#: ISO-2 → baseline + multiplier. v1 seed. Coefficients are editorial,
#: documented in CII-METHODOLOGY.md, and bumped via a method_version change.
CII_BASELINES: dict[str, CiiBaseline] = {
    "US": CiiBaseline(baseline=18.0, multiplier=0.6),
    "GB": CiiBaseline(baseline=14.0, multiplier=0.65),
    "PK": CiiBaseline(baseline=42.0, multiplier=1.15),
    "IN": CiiBaseline(baseline=24.0, multiplier=0.95),
    "CN": CiiBaseline(baseline=26.0, multiplier=0.85),
    "RU": CiiBaseline(baseline=38.0, multiplier=1.10),
    "UA": CiiBaseline(baseline=46.0, multiplier=1.25),
    "IR": CiiBaseline(baseline=44.0, multiplier=1.20),
    "IL": CiiBaseline(baseline=40.0, multiplier=1.15),
    "SA": CiiBaseline(baseline=28.0, multiplier=0.95),
    "TR": CiiBaseline(baseline=30.0, multiplier=1.0),
    "BR": CiiBaseline(baseline=22.0, multiplier=0.85),
}

#: Editorial fallback for any country not in the curated table.
DEFAULT_CII_BASELINE: CiiBaseline = CiiBaseline(baseline=15.0, multiplier=1.0)


def baseline_for(iso: str | None) -> CiiBaseline:
    """Look up a country's baseline; fall back to the default on miss."""
    if not iso:
        return DEFAULT_CII_BASELINE
    return CII_BASELINES.get(iso.upper(), DEFAULT_CII_BASELINE)
