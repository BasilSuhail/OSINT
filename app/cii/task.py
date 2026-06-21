"""CII orchestrator — reads events, aggregates per country, persists.

The body is a plain function (``_compute_cii_body``) so it can be unit
tested without going through Celery. The Celery wrapper lives in
``app.tasks`` so every task registration stays in one place.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.cii.config import CII_BASELINES, baseline_for
from app.cii.scoring import CII_METHOD_VERSION, CiiInputs, compute_cii
from app.composite.persistence import upsert_scores
from app.composite.scoring import ComposedScore
from app.db import session_scope
from app.db_models import EventRow

#: 24-hour rolling window, matching the WM CII methodology.
CII_BUCKET: timedelta = timedelta(hours=24)

#: CAMEO event root codes flagged as material conflict / fight / use of
#: unconventional violence. See app/sources/gdelt_cameo.py is_conflict_event
#: for the canonical definition.
_CONFLICT_ROOT_CODES: set[int] = {18, 19, 20}

#: Severity above which a news / uk-police row counts as "unrest signal".
#: Matches the keyword-bumped severity emitted by the RSS news fetchers.
_UNREST_SEVERITY_THRESHOLD: float = 0.6


def _is_news_row(ev: EventRow) -> bool:
    if ev.category == "news":
        return True
    source = (ev.source or "").lower()
    return source.startswith("rss-") or source == "uk-police"


def _is_conflict_row(ev: EventRow) -> bool:
    if (ev.source or "").lower() != "gdelt":
        return False
    payload = ev.payload or {}
    raw = payload.get("event_root_code")
    if raw is None:
        return False
    try:
        return int(raw) in _CONFLICT_ROOT_CODES
    except (TypeError, ValueError):
        return False


def _is_m5_quake(ev: EventRow) -> bool:
    if (ev.source or "").lower() not in {"usgs", "usgs-quake"}:
        return False
    payload = ev.payload or {}
    mag = payload.get("magnitude")
    try:
        return float(mag) >= 5.0
    except (TypeError, ValueError):
        return False


def _is_orange_red_hazard(ev: EventRow) -> bool:
    if (ev.source or "").lower() != "gdacs":
        return False
    payload = ev.payload or {}
    level = str(payload.get("alert_level") or "").lower()
    return level in {"orange", "red"}


def _aggregate(events: list[EventRow]) -> dict[str, CiiInputs]:
    """Bucket events into per-country aggregates within the 24 h window."""
    out: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "unrest_signals": 0,
            "unrest_fatalities": 0,
            "conflict_events": 0,
            "quake_m5_plus": 0,
            "hazard_orange_red": 0,
            "news_volume": 0,
        }
    )
    for ev in events:
        if not ev.country:
            continue
        iso = ev.country.upper()
        bucket = out[iso]
        if _is_news_row(ev):
            bucket["news_volume"] += 1
            sev = ev.severity if ev.severity is not None else 0.0
            if sev >= _UNREST_SEVERITY_THRESHOLD:
                bucket["unrest_signals"] += 1
                fatalities = (ev.payload or {}).get("fatalities")
                with suppress(TypeError, ValueError):
                    bucket["unrest_fatalities"] += int(fatalities or 0)
        if _is_conflict_row(ev):
            bucket["conflict_events"] += 1
        if _is_m5_quake(ev):
            bucket["quake_m5_plus"] += 1
        if _is_orange_red_hazard(ev):
            bucket["hazard_orange_red"] += 1

    return {iso: CiiInputs(**counts) for iso, counts in out.items()}


def _ensure_baseline_countries(per_country: dict[str, CiiInputs]) -> dict[str, CiiInputs]:
    """Force a row for every Tier-1 country, even if it had 0 events.

    The dashboard otherwise renders gaps for a quiet UK / US day instead of
    a flat baseline reading — and a flat baseline reading is the correct
    information here.
    """
    out = dict(per_country)
    for iso in CII_BASELINES:
        out.setdefault(iso, CiiInputs())
    return out


def _compute_cii_body(
    *,
    bucket_end: datetime | None = None,
    method_version: str = CII_METHOD_VERSION,
) -> dict[str, Any]:
    """Read 24 h of events, aggregate by country, score, upsert.

    Returns a small summary dict so the Celery task log carries something
    useful for the watchdog.
    """
    end = bucket_end or datetime.now(UTC)
    start = end - CII_BUCKET

    with session_scope() as session:
        stmt = (
            select(EventRow).where(EventRow.occurred_at >= start).where(EventRow.occurred_at < end)
        )
        events = list(session.execute(stmt).scalars())

        aggregates = _ensure_baseline_countries(_aggregate(events))
        scores: list[ComposedScore] = []
        for iso, inputs in aggregates.items():
            components = compute_cii(iso, inputs, baseline=baseline_for(iso))
            scores.append(
                ComposedScore(
                    country=iso,
                    bucket_start=start,
                    bucket_length=CII_BUCKET,
                    score_name="cii_v1",
                    score_value=components.total,
                    components=components.as_payload(),
                    method_version=method_version,
                )
            )
        upsert_scores(scores, session)
        session.commit()

    return {
        "method_version": method_version,
        "bucket_start": start.isoformat(),
        "bucket_end": end.isoformat(),
        "countries_scored": len(aggregates),
        "events_read": len(events),
    }
