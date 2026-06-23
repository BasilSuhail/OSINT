"""Pure CII v1 scoring.

Formula:
    CII = 0.40 * baseline + 0.60 * event_score
    event_score = 0.25 * unrest
                + 0.30 * conflict
                + 0.20 * security
                + 0.25 * information

Each sub-score is on a 0-100 scale and log-dampened so a single huge value
doesn't drown the others. The final CII is divided by 100 so it sits in
[0, 1] and satisfies the ``scores.score_value`` CHECK constraint.

This module is import-pure: no DB, no network. The orchestrator in
``app.cii.task`` handles aggregation off the events buffer.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from app.cii.config import CiiBaseline, baseline_for

#: Bumped together with any change to weights, sub-score formulas, or the
#: baseline table. Never edit a prior version in place.
CII_METHOD_VERSION: str = "cii.v1.2"

#: Top-level blend (baseline vs event aggregate).
_BASELINE_WEIGHT: float = 0.40
_EVENT_WEIGHT: float = 0.60

#: Event-score sub-weights — must sum to 1.0.
_UNREST_W: float = 0.25
_CONFLICT_W: float = 0.30
_SECURITY_W: float = 0.20
_INFORMATION_W: float = 0.25

assert math.isclose(_UNREST_W + _CONFLICT_W + _SECURITY_W + _INFORMATION_W, 1.0)


@dataclass(frozen=True)
class CiiInputs:
    """Raw aggregates over a 24 h window for one country.

    Counts are post-multiplier-applied at the orchestrator level so this
    module stays pure.
    """

    #: News + UK Police rows whose severity ≥ 0.6 (keyword-boosted).
    unrest_signals: int = 0
    #: Number of protest+riot fatalities reported, summed from payloads.
    unrest_fatalities: int = 0
    #: GDELT events with CAMEO root code in {18, 19, 20}.
    conflict_events: int = 0
    #: USGS earthquakes with magnitude ≥ 5.
    quake_m5_plus: int = 0
    #: GDACS alerts with alert_level in {orange, red}.
    hazard_orange_red: int = 0
    #: EONET active hazard events (NASA — wildfires, storms, floods,
    #: volcanic activity). v1.2 adds these to the Security sub-score
    #: so a country with no GDACS-grade alerts but persistent EONET
    #: hazards still registers.
    eonet_events: int = 0
    #: Any news / RSS rows in the 24 h window. Drives information stress.
    news_volume: int = 0


@dataclass(frozen=True)
class CiiComponents:
    """The numbers stored on ``scores.components`` for one country/bucket."""

    baseline: float
    unrest: float
    conflict: float
    security: float
    information: float
    event_score: float
    total: float
    multiplier: float
    method_version: str

    def as_payload(self) -> dict[str, float | str]:
        return {k: v for k, v in asdict(self).items()}


def _log_scale(raw: float, ceiling_log: float) -> float:
    """Map raw count → 0..100 via log1p, with a ceiling that becomes 100.

    ``ceiling_log = log1p(N)`` where N is the row count that should read
    as "fully saturated". Keeps a single huge value from drowning the
    rest of the components.
    """
    if raw <= 0 or ceiling_log <= 0:
        return 0.0
    return min(100.0, math.log1p(raw) / ceiling_log * 100.0)


def _unrest(inputs: CiiInputs, multiplier: float) -> float:
    """0-100. Log-scaled signal count plus a sqrt-scaled fatality bump.

    ``unrest_signals`` is the keyword-bumped severity ≥ 0.6 RSS volume,
    capped log-style so a noisy day with 1k headlines plateaus instead
    of exploding the score.
    """
    base = _log_scale(inputs.unrest_signals * multiplier, math.log1p(60))
    fatality_bump = min(30.0, math.sqrt(max(0, inputs.unrest_fatalities)) * 6.0)
    return min(100.0, base + fatality_bump)


def _conflict(inputs: CiiInputs, multiplier: float) -> float:
    """0-100. GDELT CAMEO 18/19/20 count, log-scaled."""
    return _log_scale(inputs.conflict_events * multiplier, math.log1p(400))


def _security(inputs: CiiInputs, multiplier: float) -> float:
    """0-100. M5+ quakes + GDACS orange/red + EONET active hazards.

    Quakes weigh 6 pts each (capped at 60); GDACS at 12 each (capped 60).
    EONET active hazards (NASA — wildfires, storms, floods, volcanoes)
    contribute 4 pts each (capped at 40) — softer weight because EONET
    is much higher-volume than GDACS and a single EONET event isn't as
    severe as a GDACS orange/red alert. Multiplier amplifies for fragile
    regions (UA / IR) where cascade risk on top of a hazard is
    structurally higher.

    v1.2 adds the EONET term — see CII-METHODOLOGY.md.
    """
    quake = min(60.0, inputs.quake_m5_plus * 6.0)
    hazard = min(60.0, inputs.hazard_orange_red * 12.0)
    eonet = min(40.0, inputs.eonet_events * 4.0)
    return min(100.0, (quake + hazard + eonet) * multiplier)


def _information(inputs: CiiInputs, multiplier: float) -> float:
    """0-100. News volume per 24 h, log-scaled.

    ``news_volume`` is the count of news + uk-police rows. Multiplier
    dampens the high-volume English-language feeds (US/UK) where 200
    rows is a quiet news day, not stress.
    """
    return _log_scale(inputs.news_volume * multiplier, math.log1p(300))


def compute_cii(
    country: str,
    inputs: CiiInputs,
    baseline: CiiBaseline | None = None,
) -> CiiComponents:
    """Compute one country's CII value + components for a 24 h window.

    Returns the components dataclass; the orchestrator turns this into a
    ``ScoreRow`` insert. The ``total`` field is on a 0..1 scale so it
    satisfies the existing ``scores_value_range`` CHECK constraint.
    """
    cfg = baseline or baseline_for(country)
    unrest = _unrest(inputs, cfg.multiplier)
    conflict = _conflict(inputs, cfg.multiplier)
    security = _security(inputs, cfg.multiplier)
    information = _information(inputs, cfg.multiplier)

    event_score = (
        _UNREST_W * unrest
        + _CONFLICT_W * conflict
        + _SECURITY_W * security
        + _INFORMATION_W * information
    )
    raw = _BASELINE_WEIGHT * cfg.baseline + _EVENT_WEIGHT * event_score
    total = max(0.0, min(1.0, raw / 100.0))

    return CiiComponents(
        baseline=cfg.baseline,
        unrest=unrest,
        conflict=conflict,
        security=security,
        information=information,
        event_score=event_score,
        total=total,
        multiplier=cfg.multiplier,
        method_version=CII_METHOD_VERSION,
    )
