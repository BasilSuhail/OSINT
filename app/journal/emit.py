"""Emit layer — composite score rows → immutable prediction rows.

The insert is ON CONFLICT DO NOTHING on the forecast key: once a prediction is
issued it can never be rewritten, even if the composite reruns with revised
data. That immutability is the journal's integrity claim.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db_models import PredictionRow

SOURCE: str = "composite"
HORIZONS: tuple[int, ...] = (1, 3, 6)


def _month_start(dt: datetime) -> datetime:
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return datetime(dt.year, dt.month, 1, tzinfo=UTC)


def predictions_from_scores(
    scores: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Expand each composite score into one prediction per horizon.

    Hindcast guard: a score for a month earlier than the issuance month is
    skipped — its forecast window [t+1, t+k] would overlap the known past,
    and grading it would fake a track record. Only genuinely forward
    forecasts enter the journal.
    """
    now = now or datetime.now(UTC)
    current_month = _month_start(now)
    predictions: list[dict[str, Any]] = []
    for score in scores:
        if _month_start(score["bucket_start"]) < current_month:
            continue
        for horizon in HORIZONS:
            predictions.append(
                {
                    "source": SOURCE,
                    "method_version": score["method_version"],
                    "country": score["country"],
                    "bucket_start": score["bucket_start"],
                    "horizon_months": horizon,
                    "score": float(score["score_value"]),
                    "payload": {"components": score["components"]},
                }
            )
    return predictions


def upsert_predictions(predictions: list[dict[str, Any]], session: Session) -> int:
    """Insert-if-absent; returns the number of newly issued predictions."""
    if not predictions:
        return 0

    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        base = pg_insert(PredictionRow).values(predictions)
    elif dialect == "sqlite":
        base = sqlite_insert(PredictionRow).values(predictions)
    else:
        raise NotImplementedError(
            f"upsert_predictions does not support dialect {dialect!r}; add a branch above"
        )

    stmt = base.on_conflict_do_nothing(
        index_elements=["source", "method_version", "country", "bucket_start", "horizon_months"]
    ).returning(PredictionRow.id)
    issued = len(session.execute(stmt).fetchall())
    session.commit()
    return issued
