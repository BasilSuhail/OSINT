"""Grade layer — resolve outcomes for matured prediction windows, exactly once.

A prediction is gradable only when its whole window [t+1, t+k] is in the past
AND inside the country's label coverage. Windows past-but-uncovered stay
pending: grading against unknowable truth would corrupt the track record.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import PredictionRow


def _add_months(month: datetime, n: int) -> datetime:
    total = month.year * 12 + (month.month - 1) + n
    return month.replace(year=total // 12, month=total % 12 + 1)


def _utc(dt: datetime) -> datetime:
    """SQLite loses tzinfo on DateTime(timezone=True) columns; normalise."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def resolve_outcome(
    prediction: Mapping[str, Any],
    label_months: set[tuple[str, datetime]],
    coverage: Mapping[str, tuple[datetime, datetime]],
    *,
    now: datetime,
) -> int | None:
    """Return 0/1 when the window is mature and covered, else None (pending)."""
    country = prediction["country"]
    window = [
        _add_months(_utc(prediction["bucket_start"]), offset)
        for offset in range(1, prediction["horizon_months"] + 1)
    ]

    # Mature: the month AFTER the last window month has started.
    if _add_months(window[-1], 1) > now:
        return None

    if country not in coverage:
        return None
    first, last = coverage[country]
    if window[0] < first or window[-1] > last:
        return None

    return int(any((country, month) in label_months for month in window))


def grade_pending(
    session: Session,
    label_months: set[tuple[str, datetime]],
    coverage: Mapping[str, tuple[datetime, datetime]],
    *,
    now: datetime | None = None,
) -> int:
    """Grade every ungraded prediction that has matured; returns count graded."""
    now = now or datetime.now(UTC)
    graded = 0
    pending = session.execute(
        select(PredictionRow).where(PredictionRow.outcome.is_(None))
    ).scalars()
    for row in pending:
        outcome = resolve_outcome(
            {
                "country": row.country,
                "bucket_start": row.bucket_start,
                "horizon_months": row.horizon_months,
            },
            label_months,
            coverage,
            now=now,
        )
        if outcome is None:
            continue
        row.outcome = outcome
        row.graded_at = now
        graded += 1
    session.commit()
    return graded
