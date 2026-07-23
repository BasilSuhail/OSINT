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

import contextlib
from typing import Any, Final

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db_models import EventRow
from app.events_bus import publish_new_events
from app.models import Event

#: Rows per upsert statement. 12 cols x 1000 = 12 000 bound params — well under
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


#: Columns refreshed when an event is re-reported. Snapshot feeds (GDACS
#: geteventlist, EONET open events) re-publish the SAME `(source, source_event_id)`
#: every fetch while a hazard is active; without refreshing these, an ongoing
#: wildfire / flood / cyclone would freeze at its first-seen state and eventually
#: fall out of the dashboard's live window. Identity columns (source,
#: source_event_id, category) are never updated. `payload` is handled separately
#: — see `_payload_refresh()`.
_REFRESH_COLS: Final = (
    "occurred_at",
    "fetched_at",
    "severity",
    "confidence",
    "keywords",
    "country",
    "lat",
    "lon",
)


def _payload_refresh(excluded: Any, dialect: str) -> Any:
    """Merge the incoming payload over the stored one instead of replacing it.

    Everything we add ourselves after ingestion lives in `payload`: footprint
    geometry, sentiment, NER, geo enrichment. Replacing the column on refresh
    wiped all of it every time a snapshot feed re-published an active event —
    GDACS does that every 15 minutes, which is why long-running hazards
    (droughts above all) never kept their real polygon and fell back to the
    synthesized circle on the map (#604). A shallow merge keeps the enrichment
    and still lets upstream win on any key it actually sends.
    """
    if dialect == "postgresql":
        return EventRow.payload.op("||")(excluded.payload)
    return func.json_patch(EventRow.payload, excluded.payload)


def _dedup_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate `(source, source_event_id)` within one batch, keeping
    the last occurrence — ON CONFLICT DO UPDATE cannot touch the same key twice
    in a single statement. Rows with a null id never conflict, so they pass
    through untouched.
    """
    keyed: dict[tuple[str, str], dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []
    for row in rows:
        sid = row["source_event_id"]
        if sid is None:
            passthrough.append(row)
        else:
            keyed[(row["source"], sid)] = row
    return passthrough + list(keyed.values())


def _upsert_batch(rows: list[dict[str, Any]], session: Session, dialect: str) -> int:
    """Run a single batch upsert and return the number of rows affected
    (inserted OR refreshed) via RETURNING."""
    rows = _dedup_rows(rows)
    if dialect == "postgresql":
        base = pg_insert(EventRow).values(rows)
    elif dialect == "sqlite":
        base = sqlite_insert(EventRow).values(rows)
    else:
        raise NotImplementedError(
            f"upsert_events does not support dialect {dialect!r}; add a branch above"
        )

    refreshed: dict[str, Any] = {col: base.excluded[col] for col in _REFRESH_COLS}
    refreshed["payload"] = _payload_refresh(base.excluded, dialect)
    stmt = base.on_conflict_do_update(
        index_elements=["source", "source_event_id"],
        set_=refreshed,
    )

    # RETURNING yields every affected row (inserted + updated). Both Postgres and
    # SQLite ≥ 3.35 support it, avoiding the `rowcount = -1` quirk some drivers
    # exhibit on multi-row ON CONFLICT statements.
    stmt = stmt.returning(EventRow.id)
    result = session.execute(stmt)
    return len(result.fetchall())


def upsert_events(
    events: list[Event],
    session: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Upsert events keyed on `(source, source_event_id)`.

    New rows are inserted; a row whose key already exists is REFRESHED (its
    occurred_at / fetched_at / severity / geo / payload updated from the latest
    fetch) so snapshot feeds like GDACS and EONET keep their ongoing hazards
    current instead of freezing at first-seen. Splits the input into chunks of
    `batch_size` to stay under Postgres' 65 535-parameter cap. Returns the number
    of rows affected (inserted or refreshed).
    """
    if not events:
        return 0
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    rows = [_event_to_row(e) for e in events]
    dialect = session.get_bind().dialect.name

    affected = 0
    for start in range(0, len(rows), batch_size):
        affected += _upsert_batch(rows[start : start + batch_size], session, dialect)
    # A dead Redis must never fail an ingest; the SSE clients fall back to
    # their 30s SWR poll. Swallow and continue.
    with contextlib.suppress(Exception):
        publish_new_events(affected)
    return affected
