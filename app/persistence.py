"""Database persistence for canonical events.

Single entry point: `upsert_events()`. Idempotent on the
`(source, source_event_id)` UNIQUE index so retrying a fetch never produces
duplicate rows. See `docs/architecture/03-ingestion.md` for the contract.

Batching: Postgres limits a single statement to 65 535 bound parameters
(libpq protocol). The Event row has 12 columns, so the safe ceiling per
INSERT is ⌊65535 / 12⌋ = 5 461 rows. We batch at 1 000 to keep memory and
parse cost low and to leave headroom if the row shape grows.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db_models import EventRow
from app.models import Event

#: Rows per upsert statement. 12 cols × 1000 = 12 000 bound params — well under
#: Postgres' 65 535 cap, generous headroom if columns are added later.
DEFAULT_BATCH_SIZE = 1000


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


def _upsert_batch(rows: list[dict[str, Any]], session: Session, dialect: str) -> int:
    """Run a single batch upsert and return the exact insert count via RETURNING."""
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

    # RETURNING gives an exact count of *inserted* rows (skipped conflicts are
    # not returned). Both Postgres and SQLite ≥ 3.35 support it, and this
    # avoids the `rowcount = -1` quirk some drivers exhibit on multi-row
    # ON CONFLICT statements.
    stmt = stmt.returning(EventRow.id)
    result = session.execute(stmt)
    return len(result.fetchall())


def upsert_events(
    events: list[Event],
    session: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Insert events, ignoring rows whose `(source, source_event_id)` already exists.

    Splits the input into chunks of `batch_size` to stay well under Postgres'
    65 535-parameter statement cap. Returns the exact number of rows actually
    inserted (duplicates skipped via ON CONFLICT do not count).
    """
    if not events:
        return 0
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    rows = [_event_to_row(e) for e in events]
    dialect = session.get_bind().dialect.name

    inserted = 0
    for start in range(0, len(rows), batch_size):
        inserted += _upsert_batch(rows[start : start + batch_size], session, dialect)
    return inserted
