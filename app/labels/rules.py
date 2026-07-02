"""Rules layer — tidy weekly rows → P1-P3 country-month label dicts.

Pure functions only; no I/O, no DB. Thresholds are the labels-v1.0
aggregate adaptation of methodology.md Step 2 (see
docs/superpowers/specs/2026-07-02-acled-labels-design.md). Changing any
threshold requires a new RULES_VERSION, never an in-place edit — same lock
discipline as `app.composite.config.DEFAULT_METHOD_VERSION`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

#: Version stamp carried in every label payload.
RULES_VERSION: str = "labels-v1.0"

#: P1 — weekly Battles fatalities at or above this fire an armed-conflict-onset label.
P1_BATTLE_FATALITIES_MIN: int = 10

#: P2 — weekly demonstration events (Protests + Riots) at or above this ...
P2_DEMO_EVENTS_MIN: int = 5
#: ... with at least this many Riots events in the same week.
P2_RIOT_EVENTS_MIN: int = 1

#: P3 — month-over-month multiplier on political-violence fatalities ...
P3_MULTIPLIER: float = 2.0
#: ... with an absolute floor so 1 → 2 fatalities never fires.
P3_FATALITIES_FLOOR: int = 25

#: Event types counted as political violence for P3 (ACLED convention;
#: Protests are demonstrations, not political violence).
POLITICAL_VIOLENCE_EVENT_TYPES: frozenset[str] = frozenset(
    {"Battles", "Explosions/Remote violence", "Violence against civilians", "Riots"}
)

DEMONSTRATION_EVENT_TYPES: frozenset[str] = frozenset({"Protests", "Riots"})


def month_start_utc(dt: datetime) -> datetime:
    """Truncate a datetime to the first day of its month in UTC."""
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return datetime(dt.year, dt.month, 1, tzinfo=UTC)


def _next_month(month: datetime) -> datetime:
    if month.month == 12:
        return datetime(month.year + 1, 1, 1, tzinfo=UTC)
    return datetime(month.year, month.month + 1, 1, tzinfo=UTC)


def _label(
    country: str,
    bucket_start: datetime,
    code: str,
    magnitude: float,
    detail: dict[str, Any],
) -> dict[str, Any]:
    return {
        "country": country,
        "bucket_start": bucket_start,
        "label_code": code,
        "magnitude": magnitude,
        "payload": {"rules_version": RULES_VERSION, **detail},
    }


def compute_labels(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Apply P1-P3 to tidy weekly rows and return country-month label dicts.

    Input items must expose: country (ISO2), week (datetime), event_type,
    events (int), fatalities (int).
    """
    # (country, week) accumulators
    battle_fatalities: dict[tuple[str, datetime], int] = defaultdict(int)
    demo_events: dict[tuple[str, datetime], int] = defaultdict(int)
    riot_events: dict[tuple[str, datetime], int] = defaultdict(int)
    # (country, month) accumulator for P3
    pv_fatalities: dict[tuple[str, datetime], int] = defaultdict(int)
    observed_months: dict[str, set[datetime]] = defaultdict(set)

    for row in rows:
        country = row["country"]
        week = row["week"]
        week = week.replace(tzinfo=UTC) if week.tzinfo is None else week.astimezone(UTC)
        event_type = row["event_type"]
        events = int(row["events"])
        fatalities = int(row["fatalities"])
        month = month_start_utc(week)
        observed_months[country].add(month)

        if event_type == "Battles":
            battle_fatalities[(country, week)] += fatalities
        if event_type in DEMONSTRATION_EVENT_TYPES:
            demo_events[(country, week)] += events
        if event_type == "Riots":
            riot_events[(country, week)] += events
        if event_type in POLITICAL_VIOLENCE_EVENT_TYPES:
            pv_fatalities[(country, month)] += fatalities

    labels: list[dict[str, Any]] = []
    labels.extend(_p1_labels(battle_fatalities))
    labels.extend(_p2_labels(demo_events, riot_events))
    labels.extend(_p3_labels(pv_fatalities, observed_months))
    labels.sort(key=lambda lab: (lab["country"], lab["bucket_start"], lab["label_code"]))
    return labels


def _p1_labels(
    battle_fatalities: Mapping[tuple[str, datetime], int],
) -> list[dict[str, Any]]:
    by_month: dict[tuple[str, datetime], list[tuple[datetime, int]]] = defaultdict(list)
    for (country, week), fatalities in battle_fatalities.items():
        if fatalities >= P1_BATTLE_FATALITIES_MIN:
            by_month[(country, month_start_utc(week))].append((week, fatalities))

    labels = []
    for (country, month), weeks in by_month.items():
        weeks.sort()
        labels.append(
            _label(
                country,
                month,
                "P1",
                float(max(f for _, f in weeks)),
                {
                    "trigger_weeks": [w.date().isoformat() for w, _ in weeks],
                    "weekly_battle_fatalities": [f for _, f in weeks],
                },
            )
        )
    return labels


def _p2_labels(
    demo_events: Mapping[tuple[str, datetime], int],
    riot_events: Mapping[tuple[str, datetime], int],
) -> list[dict[str, Any]]:
    by_month: dict[tuple[str, datetime], list[tuple[datetime, int]]] = defaultdict(list)
    for (country, week), events in demo_events.items():
        riots = riot_events.get((country, week), 0)
        if events >= P2_DEMO_EVENTS_MIN and riots >= P2_RIOT_EVENTS_MIN:
            by_month[(country, month_start_utc(week))].append((week, events))

    labels = []
    for (country, month), weeks in by_month.items():
        weeks.sort()
        labels.append(
            _label(
                country,
                month,
                "P2",
                float(max(e for _, e in weeks)),
                {
                    "trigger_weeks": [w.date().isoformat() for w, _ in weeks],
                    "weekly_demonstration_events": [e for _, e in weeks],
                },
            )
        )
    return labels


def _p3_labels(
    pv_fatalities: Mapping[tuple[str, datetime], int],
    observed_months: Mapping[str, set[datetime]],
) -> list[dict[str, Any]]:
    labels = []
    for country, months in observed_months.items():
        first = min(months)
        last = max(months)
        # Walk calendar months so a silent month counts as zero, but never
        # label the first observed month (no prior to compare against).
        month = _next_month(first)
        while month <= last:
            prev = pv_fatalities.get((country, _prev_month(month)), 0)
            cur = pv_fatalities.get((country, month), 0)
            if cur >= P3_FATALITIES_FLOOR and cur >= P3_MULTIPLIER * prev:
                labels.append(
                    _label(
                        country,
                        month,
                        "P3",
                        float(cur),
                        {
                            "previous_month_fatalities": prev,
                            "current_month_fatalities": cur,
                        },
                    )
                )
            month = _next_month(month)
    return labels


def _prev_month(month: datetime) -> datetime:
    if month.month == 1:
        return datetime(month.year - 1, 12, 1, tzinfo=UTC)
    return datetime(month.year, month.month - 1, 1, tzinfo=UTC)
