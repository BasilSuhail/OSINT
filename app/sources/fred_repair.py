"""Repair FRED severities erased by the former moving fetch boundary.

Run after deploying the padded fetch window::

    python -m app.sources.fred_repair

The repair derives scores only from values already retained in each series and
only fills null severity cells. Re-running it is safe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.db_models import EventRow
from app.sources.fred_fetcher import severity_for_values

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepairResult:
    """Counts from one retained-row repair pass."""

    examined: int
    repaired: int
    skipped_invalid: int


def repair_fred_severity(session: Session) -> RepairResult:
    """Fill repairable null FRED severities from retained payload history."""
    rows = list(
        session.scalars(
            select(EventRow)
            .where(EventRow.source == "fred")
            .order_by(EventRow.occurred_at, EventRow.id)
        )
    )
    by_series: dict[str, list[tuple[EventRow, float]]] = {}
    skipped_invalid = 0
    for row in rows:
        series_id = row.payload.get("series_id")
        value = row.payload.get("value")
        if not isinstance(series_id, str) or not isinstance(value, int | float):
            skipped_invalid += 1
            continue
        by_series.setdefault(series_id, []).append((row, float(value)))

    repaired = 0
    for pairs in by_series.values():
        severities = severity_for_values([value for _, value in pairs])
        for (row, _), severity in zip(pairs, severities, strict=True):
            if row.severity is None and severity is not None:
                row.severity = severity
                repaired += 1

    return RepairResult(
        examined=len(rows),
        repaired=repaired,
        skipped_invalid=skipped_invalid,
    )


def main() -> None:
    """Run the repair against the configured database."""
    with session_scope() as session:
        result = repair_fred_severity(session)
    logger.info(
        "fred severity repair: examined=%d repaired=%d skipped_invalid=%d",
        result.examined,
        result.repaired,
        result.skipped_invalid,
    )


if __name__ == "__main__":
    main()
