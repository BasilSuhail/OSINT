"""Composite worker — pulls events, runs the pipeline, persists scores.

The body is a plain function (`_compute_composite_body`) so it can be unit
tested without going through Celery. The Celery task lives in `app.tasks` to
keep all task registrations in one place.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.composite.aggregation import aggregate_events_to_domain_signals
from app.composite.config import DEFAULT_METHOD_VERSION, WeightingConfig
from app.composite.history import load_signals, merge_signals, persist_signals
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

#: Rows the driver buffers per round trip while streaming events. The lookback
#: window holds more events than the worker's memory ceiling can hold objects
#: for, so they are aggregated a chunk at a time rather than read into a list.
EVENT_STREAM_CHUNK: int = 10_000


def _compute_composite_body(
    *,
    method_version: str = DEFAULT_METHOD_VERSION,
    lookback_months: int = DEFAULT_LOOKBACK_MONTHS,
    weights: WeightingConfig | None = None,
) -> dict[str, Any]:
    """Pure orchestrator — read events, aggregate, normalize, score, upsert."""
    cutoff = datetime.now(UTC) - timedelta(days=30 * lookback_months)

    events_read = 0

    with session_scope() as session:
        rows = session.execute(
            select(
                EventRow.country,
                EventRow.category,
                EventRow.severity,
                EventRow.occurred_at,
                EventRow.source,
                EventRow.payload["frp"].as_string().label("frp"),
            )
            .where(EventRow.occurred_at >= cutoff)
            .where(EventRow.category.in_(COMPOSITE_CATEGORIES))
            .where(EventRow.severity.isnot(None))
            .where(EventRow.country.isnot(None))
            .execution_options(yield_per=EVENT_STREAM_CHUNK)
        )

        def _stream() -> Iterator[dict[str, Any]]:
            nonlocal events_read
            for r in rows:
                events_read += 1
                yield {
                    "country": r.country,
                    "category": r.category,
                    "severity": r.severity,
                    "occurred_at": r.occurred_at,
                    # FIRMS is routed to the wildfire domain by source, and
                    # summed on FRP rather than max'd on severity (#579).
                    "source": r.source,
                    "frp": r.frp,
                }

        # Aggregation consumes the stream inside the session, so the rows are
        # never all alive at once.
        aggregated = aggregate_events_to_domain_signals(_stream())

    # Record this run's months, then normalise against everything on record —
    # not just what survived retention. Rebuilding history from the events
    # table alone left 183 of 184 countries below MIN_HISTORY, so every z-score
    # was 0 and every live composite score was exactly 0.5 (#586).
    with session_scope() as session:
        persist_signals(aggregated, session)
        history = load_signals(session, since=cutoff)
    signals = merge_signals(history, aggregated)

    normalized = normalize_domain_signals(signals)
    scores = compute_scores(
        normalized,
        weights=weights,
        method_version=method_version,
    )

    with session_scope() as session:
        upserted = upsert_scores(scores, session)

    return {
        "events_read": events_read,
        "buckets_aggregated": len(aggregated),
        "months_on_record": len(signals),
        "scores_written": len(scores),
        "rows_upserted": upserted,
        "method_version": method_version,
    }
