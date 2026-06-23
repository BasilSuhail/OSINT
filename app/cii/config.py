"""Per-country baselines + event multipliers for CII v1.

The 31-country Tier-1 list now matches koala73/worldmonitor's CII v8.
Countries outside the table fall back to ``DEFAULT_CII_BASELINE``
(baseline=15, multiplier=1.0). Numbers are editorial defaults — they
get revisited every methodology version bump.

Reference: koala73/worldmonitor ``docs/algorithms.mdx`` § "Country
Instability Index (CII)". 12 → 31 expansion landed via cii.v1.1.
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


#: ISO-2 → baseline + multiplier. Coefficients are editorial,
#: documented in CII-METHODOLOGY.md, and bumped via a method_version change.
CII_BASELINES: dict[str, CiiBaseline] = {
    # Original 12-country v1.0 seed
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
    "TR": CiiBaseline(baseline=30.0, multiplier=1.00),
    "BR": CiiBaseline(baseline=22.0, multiplier=0.85),
    # cii.v1.1 expansion to match WM CII v8 (+ 19 countries)
    "TW": CiiBaseline(baseline=32.0, multiplier=1.05),
    "KP": CiiBaseline(baseline=46.0, multiplier=1.20),
    "PL": CiiBaseline(baseline=20.0, multiplier=0.90),
    "DE": CiiBaseline(baseline=14.0, multiplier=0.65),
    "FR": CiiBaseline(baseline=18.0, multiplier=0.75),
    "SY": CiiBaseline(baseline=48.0, multiplier=1.30),
    "YE": CiiBaseline(baseline=48.0, multiplier=1.30),
    "MM": CiiBaseline(baseline=44.0, multiplier=1.25),
    "VE": CiiBaseline(baseline=38.0, multiplier=1.10),
    "CU": CiiBaseline(baseline=30.0, multiplier=1.00),
    "MX": CiiBaseline(baseline=28.0, multiplier=0.95),
    "AE": CiiBaseline(baseline=20.0, multiplier=0.85),
    "KR": CiiBaseline(baseline=18.0, multiplier=0.80),
    "IQ": CiiBaseline(baseline=42.0, multiplier=1.20),
    "AF": CiiBaseline(baseline=48.0, multiplier=1.30),
    "LB": CiiBaseline(baseline=42.0, multiplier=1.15),
    "EG": CiiBaseline(baseline=30.0, multiplier=1.00),
    "JP": CiiBaseline(baseline=14.0, multiplier=0.65),
    "QA": CiiBaseline(baseline=18.0, multiplier=0.85),
}

#: Editorial fallback for any country not in the curated table.
DEFAULT_CII_BASELINE: CiiBaseline = CiiBaseline(baseline=15.0, multiplier=1.0)


def baseline_for(iso: str | None) -> CiiBaseline:
    """Look up a country's baseline; fall back to the default on miss."""
    if not iso:
        return DEFAULT_CII_BASELINE
    return CII_BASELINES.get(iso.upper(), DEFAULT_CII_BASELINE)
