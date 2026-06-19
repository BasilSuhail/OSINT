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
    """Bulk-upsert composite scores. Returns number of rows touched."""
    if not scores:
        return 0

    rows = [_score_to_row(s) for s in scores]
    bind = session.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        stmt = pg_insert(ScoreRow).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=list(_CONFLICT_KEYS),
            set_={
                "score_value": stmt.excluded.score_value,
                "components": stmt.excluded.components,
            },
        )
    elif dialect == "sqlite":
        stmt = sqlite_insert(ScoreRow).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=list(_CONFLICT_KEYS),
            set_={
                "score_value": stmt.excluded.score_value,
                "components": stmt.excluded.components,
            },
        )
    else:
        raise NotImplementedError(
            f"upsert_scores does not support dialect {dialect!r}; add a branch above"
        )

    result = session.execute(stmt)
    return result.rowcount or 0
