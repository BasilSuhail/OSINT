"""Composite worker — pulls events, runs the pipeline, persists scores.

The body is a plain function (`_compute_composite_body`) so it can be unit
tested without going through Celery. The Celery task lives in `app.tasks` to
keep all task registrations in one place.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.composite.aggregation import aggregate_events_to_domain_signals
from app.composite.config import DEFAULT_METHOD_VERSION, WeightingConfig
from app.composite.normalization import normalize_domain_signals
from app.composite.persistence import upsert_scores
from app.composite.scoring import compute_scores
from app.db import session_scope
from app.db_models import EventRow

#: How far back in months the composite worker reads events. Two years gives
#: the rolling z-score enough history to warm up before the latest month.
DEFAULT_LOOKBACK_MONTHS: int = 24

#: Composite categories — anything else stays out of the composite per
#: docs/architecture/04-schema.md.
COMPOSITE_CATEGORIES = ("market", "geopolitical", "hazard")


def _compute_composite_body(
    *,
    method_version: str = DEFAULT_METHOD_VERSION,
    lookback_months: int = DEFAULT_LOOKBACK_MONTHS,
    weights: WeightingConfig | None = None,
) -> dict[str, Any]:
    """Pure orchestrator — read events, aggregate, normalize, score, upsert."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30 * lookback_months)

    with session_scope() as session:
        rows = session.execute(
            select(
                EventRow.country,
                EventRow.category,
                EventRow.severity,
                EventRow.occurred_at,
            )
            .where(EventRow.occurred_at >= cutoff)
            .where(EventRow.category.in_(COMPOSITE_CATEGORIES))
            .where(EventRow.severity.isnot(None))
            .where(EventRow.country.isnot(None))
        ).all()
        events = [
            {
                "country": r.country,
                "category": r.category,
                "severity": r.severity,
                "occurred_at": r.occurred_at,
            }
            for r in rows
        ]

    aggregated = aggregate_events_to_domain_signals(events)
    normalized = normalize_domain_signals(aggregated)
    scores = compute_scores(
        normalized,
        weights=weights,
        method_version=method_version,
    )

    with session_scope() as session:
        upserted = upsert_scores(scores, session)

    return {
        "events_read": len(events),
        "buckets_aggregated": len(aggregated),
        "scores_written": len(scores),
        "rows_upserted": upserted,
        "method_version": method_version,
    }
