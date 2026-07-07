"""Persistence for composite scores.

Idempotent: on conflict over (country, bucket_start, bucket_length, score_name,
method_version) the row is refreshed with the latest score_value and components.
This is the right behaviour for the composite — recomputation with the same
method_version should overwrite stale rows rather than skip them.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.composite.scoring import ComposedScore
from app.db_models import ScoreRow

_CONFLICT_KEYS = (
    "country",
    "bucket_start",
    "bucket_length",
    "score_name",
    "method_version",
)

#: Postgres caps bind parameters at 65,535 per statement. A full three-domain
#: backfill upserts ~24k score rows at 7 parameters each, so the upsert is
#: chunked (same convention as the labels upsert).
BATCH_SIZE = 5_000


def _score_to_row(score: ComposedScore) -> dict[str, Any]:
    return {
        "country": score.country,
        "bucket_start": score.bucket_start,
        "bucket_length": score.bucket_length,
        "score_name": score.score_name,
        "score_value": score.score_value,
        "components": score.components,
        "method_version": score.method_version,
    }


def upsert_scores(scores: list[ComposedScore], session: Session) -> int:
    """Bulk-upsert composite scores in batches. Returns number of rows touched."""
    if not scores:
        return 0

    rows = [_score_to_row(s) for s in scores]
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        insert = pg_insert
    elif dialect == "sqlite":
        insert = sqlite_insert
    else:
        raise NotImplementedError(
            f"upsert_scores does not support dialect {dialect!r}; add a branch above"
        )

    touched = 0
    for start in range(0, len(rows), BATCH_SIZE):
        stmt = insert(ScoreRow).values(rows[start : start + BATCH_SIZE])
        stmt = stmt.on_conflict_do_update(
            index_elements=list(_CONFLICT_KEYS),
            set_={
                "score_value": stmt.excluded.score_value,
                "components": stmt.excluded.components,
            },
        )
        touched += session.execute(stmt).rowcount or 0
    return touched
