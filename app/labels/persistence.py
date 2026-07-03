"""Persistence layer — idempotent upsert of label dicts into the labels table.

Keyed on (country, bucket_start, label_code, label_source) so reruns refresh
magnitude/payload instead of duplicating rows — same pattern as
`app.persistence.upsert_events`. A rules-version bump changes which rows
qualify, so the run first purges rows written under older versions — labels
are fully derived data and regeneration is a full refresh per label_source.
"""

from __future__ import annotations

import calendar
from datetime import timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db_models import LabelRow

#: Stamped on every row this labeler writes; P4/P5 labelers will use their own.
LABEL_SOURCE: str = "acled-aggregates"

_REFRESH_COLS = ("magnitude", "payload", "bucket_length")


def _month_length(bucket_start: Any) -> timedelta:
    days = calendar.monthrange(bucket_start.year, bucket_start.month)[1]
    return timedelta(days=days)


def _dedup(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate keys within one batch, keeping the last occurrence —
    ON CONFLICT DO UPDATE cannot touch the same key twice in a single statement.
    """
    keyed: dict[tuple[str, Any, str, str], dict[str, Any]] = {}
    for row in rows:
        keyed[(row["country"], row["bucket_start"], row["label_code"], row["label_source"])] = row
    return list(keyed.values())


#: 7 parameters per row; stays comfortably under Postgres' 65 535-parameter cap.
DEFAULT_BATCH_SIZE: int = 5000


def purge_label_source(session: Session) -> int:
    """Delete every row this labeler owns; returns rows removed.

    Called before a full re-labeling run so rows written under an older
    rules version can never linger next to current ones.
    """
    result = session.execute(delete(LabelRow).where(LabelRow.label_source == LABEL_SOURCE))
    return result.rowcount or 0


def upsert_labels(
    labels: list[dict[str, Any]], session: Session, *, batch_size: int = DEFAULT_BATCH_SIZE
) -> int:
    """Upsert label dicts (from `app.labels.rules.compute_labels`) and return
    the number of rows affected (inserted or refreshed)."""
    if not labels:
        return 0
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    rows = _dedup(
        [
            {
                "country": label["country"],
                "bucket_start": label["bucket_start"],
                "bucket_length": _month_length(label["bucket_start"]),
                "label_code": label["label_code"],
                "label_source": LABEL_SOURCE,
                "magnitude": label["magnitude"],
                "payload": label["payload"],
            }
            for label in labels
        ]
    )

    dialect = session.get_bind().dialect.name
    affected = 0
    for start in range(0, len(rows), batch_size):
        affected += _upsert_batch(rows[start : start + batch_size], session, dialect)
    session.commit()
    return affected


def _upsert_batch(rows: list[dict[str, Any]], session: Session, dialect: str) -> int:
    if dialect == "postgresql":
        base = pg_insert(LabelRow).values(rows)
    elif dialect == "sqlite":
        base = sqlite_insert(LabelRow).values(rows)
    else:
        raise NotImplementedError(
            f"upsert_labels does not support dialect {dialect!r}; add a branch above"
        )

    stmt = base.on_conflict_do_update(
        index_elements=["country", "bucket_start", "label_code", "label_source"],
        set_={col: base.excluded[col] for col in _REFRESH_COLS},
    ).returning(LabelRow.id)
    return len(session.execute(stmt).fetchall())
