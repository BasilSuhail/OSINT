"""Database persistence for canonical events.

Single entry point: `upsert_events()`. Idempotent on the
`(source, source_event_id)` UNIQUE index so retrying a fetch never produces
duplicate rows. See `docs/architecture/03-ingestion.md` for the contract.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db_models import EventRow
from app.models import Event


def _event_to_row(event: Event) -> dict[str, Any]:
    """Convert a Pydantic `Event` to a row dict suitable for bulk insert."""
    return {
        "source": event.source,
        "source_event_id": event.source_event_id,
        "occurred_at": event.occurred_at,
        "fetched_at": event.fetched_at,
        "category": event.category.value,
        "severity": event.severity,
        "confidence": event.confidence,
        "keywords": list(event.keywords),
        "country": event.country,
        "lat": event.lat,
        "lon": event.lon,
        "payload": event.payload,
    }


def upsert_events(events: list[Event], session: Session) -> int:
    """Insert events, ignoring rows whose `(source, source_event_id)` already exists.

    Returns the number of rows actually inserted (i.e. minus any duplicates).
    """
    if not events:
        return 0

    rows = [_event_to_row(e) for e in events]

    bind = session.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        stmt = pg_insert(EventRow).values(rows).on_conflict_do_nothing(
            index_elements=["source", "source_event_id"]
        )
    elif dialect == "sqlite":
        stmt = sqlite_insert(EventRow).values(rows).on_conflict_do_nothing(
            index_elements=["source", "source_event_id"]
        )
    else:
        raise NotImplementedError(
            f"upsert_events does not support dialect {dialect!r}; add a branch above"
        )

    result = session.execute(stmt)
    return result.rowcount or 0
