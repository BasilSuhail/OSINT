"""Clear meaningless severity from retained OpenSky rows (#865).

Report-only by default. Run inside the application container so the repair uses
the same database configuration as ingestion:

    python -m app.sources.opensky_severity_repair
    python -m app.sources.opensky_severity_repair --apply

Only the known legacy value, 0.0, is cleared. An unexpected nonzero severity is
reported and preserved so this repair cannot erase a future intensity model.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import session_scope
from app.db_models import EventRow
from app.sources.opensky_fetcher import OpenSkyFetcher

DEFAULT_BATCH_SIZE: int = 5_000


@dataclass(frozen=True)
class RepairPlan:
    """Current retained-row states; produced without writing anything."""

    zero_rows: int = 0
    null_rows: int = 0
    unexpected_rows: int = 0

    @property
    def total_rows(self) -> int:
        return self.zero_rows + self.null_rows + self.unexpected_rows


def plan_repair(session: Session, *, source: str = OpenSkyFetcher.name) -> RepairPlan:
    """Count what would change and what the repair deliberately preserves."""
    rows = session.execute(
        select(EventRow.severity, func.count())
        .where(EventRow.source == source)
        .group_by(EventRow.severity)
    ).all()
    zero = null = unexpected = 0
    for severity, count in rows:
        if severity is None:
            null += count
        elif float(severity) == 0.0:
            zero += count
        else:
            unexpected += count
    return RepairPlan(zero_rows=zero, null_rows=null, unexpected_rows=unexpected)


def apply_repair(
    session: Session,
    *,
    source: str = OpenSkyFetcher.name,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Clear legacy zero severity in bounded, restart-safe batches."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    changed = 0
    while True:
        ids = list(
            session.execute(
                select(EventRow.id)
                .where(EventRow.source == source, EventRow.severity == 0.0)
                .order_by(EventRow.id)
                .limit(batch_size)
            ).scalars()
        )
        if not ids:
            break
        updated = session.execute(
            update(EventRow)
            .where(
                EventRow.id.in_(ids),
                EventRow.source == source,
                EventRow.severity == 0.0,
            )
            .values(severity=None)
            .returning(EventRow.id)
        ).scalars()
        changed += len(list(updated))
        session.commit()
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="clear legacy zero severities")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="rows per UPDATE (default: %(default)s)",
    )
    args = parser.parse_args()

    with session_scope() as session:
        plan = plan_repair(session)
        print(f"{plan.total_rows:,} OpenSky row(s) stored.")
        print(f"  {plan.zero_rows:,} legacy zero severities would be cleared.")
        print(f"  {plan.null_rows:,} already carry no severity.")
        if plan.unexpected_rows:
            print(f"  {plan.unexpected_rows:,} unexpected nonzero values will be preserved.")
        if not plan.zero_rows:
            print("nothing to do.")
            return 0
        if not args.apply:
            print("dry run — pass --apply to write.")
            return 0
        changed = apply_repair(session, batch_size=args.batch_size)
        print(f"{changed:,} row(s) updated.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI shell
    raise SystemExit(main())
