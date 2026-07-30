"""Aggregation layer — events → per-(country, month, domain) signal.

Pure functions only. Composite worker calls these over events fetched from the
events table; tests call them with plain dicts.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

#: Categories eligible for the composite. Events with other categories are
#: ignored.
COMPOSITE_CATEGORIES: frozenset[str] = frozenset({"market", "geopolitical", "hazard"})

#: FIRMS is stored as `category="hazard"` — it is a hazard, and the map and
#: detail views should keep treating it as one. It is routed to its own domain
#: by *source* rather than by category so 536,097 stored rows and every
#: frontend filter stay exactly as they are (#579).
WILDFIRE_SOURCE: str = "nasa-firms"

#: The fourth domain. Thermal load, not harm.
WILDFIRE_DOMAIN: str = "wildfire"

#: Conflict is counted, not graded (#680). The GDELT parser keeps only
#: escalatory CAMEO root codes (14-20), so every stored row already has
#: severity >= 0.700 — `severity = (10 - goldstein) / 20` and the filter admits
#: nothing above goldstein -4.0. Reading severity off a stream where every row
#: is severe said the same thing everywhere: mean 0.9863, sd 0.0523 across 168
#: countries, which z-scores to nothing at all.
#:
#: Aggregation was not the cause and swapping it would not have helped — the
#: cell mean measured sd 0.0511, no better than the max. The information is in
#: how many, not how bad: log-scaled counts measured sd 0.797, fifteen times the
#: spread. Same move #579 made for FIRMS, for the same reason.
GEOPOLITICAL_DOMAIN: str = "geopolitical"

#: Every domain the aggregator can emit.
COMPOSITE_DOMAINS: frozenset[str] = COMPOSITE_CATEGORIES | {WILDFIRE_DOMAIN}


def month_start_utc(dt: datetime) -> datetime:
    """Truncate a datetime to the first day of its month in UTC."""
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return datetime(dt.year, dt.month, 1, tzinfo=UTC)


def conflict_signal(event_count: int) -> float:
    """Country-month count of escalatory conflict events as a signal value.

    `log10(1 + count)`, so this is the second domain whose raw signal is not a
    [0, 1] severity — because it is not a severity. It is conflict load: how many
    escalatory events this country recorded this month.

    Log, because counts span orders of magnitude — 1 event to 34,715 in the live
    data. And crucially, raw counts measure *media attention* before they measure
    conflict: the US records more conflict events than Russia and Israel
    combined, and Canada outranks both. Normalisation z-scores within country
    across months, so a loud country's baseline cancels and only its own
    movement survives — the same reasoning README section 5.3 gives for judging
    loud and quiet countries on their own terms. This must never become a
    cross-country level.
    """
    return math.log10(1.0 + max(0, event_count))


def wildfire_signal(total_frp_mw: float) -> float:
    """Country-month total fire radiative power (MW) as a signal value.

    `log10(1 + total)`, so this is the one domain whose raw signal is not a
    [0, 1] severity — because it is not a severity. It is fire load: how much
    energy this country's fires radiated this month. Normalisation z-scores
    every domain before scoring, so the units never have to match; pretending
    they did is what put a fire pixel above a fatal earthquake.

    Log, because country-month totals span orders of magnitude between a
    quiet country and a fire season.
    """
    return math.log10(1.0 + max(0.0, total_frp_mw))


def aggregate_events_to_domain_signals(
    events: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, datetime], dict[str, float]]:
    """Group events by (country, month-start) into one signal per domain.

    Input items must expose at least: country, category, severity, occurred_at.
    FIRMS items additionally expose source and frp. Items missing any required
    field, or with a category outside the composite set, are silently skipped.

    **Discrete domains — market, geopolitical, hazard — take the month's
    strongest event, not its mean** (#574). Averaging diluted exactly the
    extremes the signal exists to catch: measured on live hazard data, US
    scored mean 0.095 against a max of 1.000, so a country having a catastrophe
    in a busy month read as calmer than a quiet country with one moderate
    event. #528 established the same point on the backtest side, where counting
    rows left 11 of 16 scored events with no measurement at all.

    **FIRMS takes the month's total FRP instead, in its own domain** (#579).
    Two separate reasons, and both had to be fixed together:

    1. *Wrong bucket.* A VIIRS pixel is a heat signature; a USGS row is a
       measured earthquake with casualties attached. Under `max` in a shared
       hazard domain the fire pixel simply won — 55% of country-months pinned
       at exactly 0.90 (#580), which is the hazard domain answering "did this
       country have a fire this month" and nothing else.
    2. *Wrong aggregation.* `max` over half a million pixels is the hottest
       single pixel, which saturates and barely moves month to month. The
       quantity that actually varies is how much fire there was — the sum.

    Returns: {(country_iso, month_start): {domain: float}} over
    COMPOSITE_DOMAINS. Missing domains are simply absent from the inner dict.
    """
    strongest: dict[tuple[str, datetime], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    frp_totals: dict[tuple[str, datetime], float] = defaultdict(float)
    conflict_counts: dict[tuple[str, datetime], int] = defaultdict(int)

    for event in events:
        country = event.get("country")
        category = event.get("category")
        occurred_at = event.get("occurred_at")
        if country is None or category is None or occurred_at is None:
            continue
        if category not in COMPOSITE_CATEGORIES:
            continue
        bucket_start = month_start_utc(occurred_at)

        if category == GEOPOLITICAL_DOMAIN:
            # Counted, not graded (#680). No severity check: counting does not
            # need one, so a row missing severity is no longer a reason to
            # discard the evidence that something happened.
            conflict_counts[(country, bucket_start)] += 1
            continue

        if event.get("source") == WILDFIRE_SOURCE:
            frp = event.get("frp")
            if frp is None:
                continue
            try:
                frp_f = float(frp)
            except (TypeError, ValueError):
                continue
            if frp_f != frp_f or frp_f == float("inf") or frp_f < 0.0:  # NaN, inf, negative
                continue
            frp_totals[(country, bucket_start)] += frp_f
            continue

        severity = event.get("severity")
        if severity is None:
            continue
        try:
            severity_f = float(severity)
        except (TypeError, ValueError):
            continue
        strongest[(country, bucket_start)][category].append(severity_f)

    out: dict[tuple[str, datetime], dict[str, float]] = {
        key: {domain: max(values) for domain, values in inner.items()}
        for key, inner in strongest.items()
    }
    for key, total in frp_totals.items():
        out.setdefault(key, {})[WILDFIRE_DOMAIN] = wildfire_signal(total)
    for key, count in conflict_counts.items():
        out.setdefault(key, {})[GEOPOLITICAL_DOMAIN] = conflict_signal(count)
    return out
