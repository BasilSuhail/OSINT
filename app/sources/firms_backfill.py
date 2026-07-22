"""Recover severity on FIRMS rows stored before #574 (#577).

#574 taught `confidence_to_severity` to read VIIRS `l`/`n`/`h`, but a fetcher
fix only reaches rows fetched after it. 462,643 rows were already in the events
table with severity NULL, and the composite reads that table on a 24-month
lookback — so the domain #574 was written to unblind stayed blind to 86% of its
own input.

Nothing needs re-fetching. `payload.confidence_raw` is present on every FIRMS
row ever stored, including all of the NULL-severity ones, so the value is
recoverable in place.

The work is grouped by distinct `confidence_raw` rather than done per row.
VIIRS emits three values, so half a million rows resolve to three UPDATEs; a
numeric MODIS product would be at most 101. Row-at-a-time would be 462k writes
to reach the same state.

Reporting and writing are separate calls, as in #553's gist sweep: this mutates
stored rows, so the counts are worth reading before anything is written.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db_models import EventRow
from app.sources.nasa_firms_fetcher import NasaFirmsFetcher, confidence_to_severity

#: JSON path to the raw confidence the fetcher has always stored. Written via
#: SQLAlchemy's JSON accessor rather than `->>` so the same code runs against
#: the SQLite used by the unit suite and the Postgres used in anger.
_CONFIDENCE_RAW = EventRow.payload["confidence_raw"].as_string()


@dataclass(frozen=True)
class BackfillGroup:
    """One distinct stored confidence value and the severity it resolves to."""

    confidence_raw: str
    severity: float
    rows: int


@dataclass(frozen=True)
class BackfillPlan:
    """What a backfill would do. Produced without writing anything."""

    groups: tuple[BackfillGroup, ...] = ()
    #: Rows whose stored confidence yields no severity — absent, empty, or
    #: unparseable. Reported so they are visible rather than silently skipped.
    unrecoverable_rows: int = 0

    @property
    def total_rows(self) -> int:
        """Rows this plan would actually give a severity to."""
        return sum(group.rows for group in self.groups)


def plan_backfill(session: Session, *, source: str = NasaFirmsFetcher.name) -> BackfillPlan:
    """Count what is recoverable, grouped by distinct confidence. Writes nothing."""
    rows = session.execute(
        select(_CONFIDENCE_RAW, func.count())
        .where(EventRow.source == source)
        .where(EventRow.severity.is_(None))
        .group_by(_CONFIDENCE_RAW)
    ).all()

    groups: list[BackfillGroup] = []
    unrecoverable = 0
    for confidence_raw, count in rows:
        severity = confidence_to_severity(confidence_raw)
        if severity is None:
            unrecoverable += count
            continue
        groups.append(BackfillGroup(confidence_raw=confidence_raw, severity=severity, rows=count))

    groups.sort(key=lambda group: group.rows, reverse=True)
    return BackfillPlan(groups=tuple(groups), unrecoverable_rows=unrecoverable)


def apply_backfill(
    session: Session, plan: BackfillPlan, *, source: str = NasaFirmsFetcher.name
) -> int:
    """Write the plan's severities. Returns the number of rows updated.

    Re-asserts `severity IS NULL` in each UPDATE rather than trusting the plan's
    counts, so a concurrent fetch that lands between planning and applying
    cannot be overwritten. That also makes this idempotent — a second run
    matches nothing.
    """
    updated = 0
    for group in plan.groups:
        result = session.execute(
            update(EventRow)
            .where(EventRow.source == source)
            .where(EventRow.severity.is_(None))
            # SIM300 reads this as a Yoda condition. It is not — a SQLAlchemy
            # comparison must lead with the column to build a SQL expression.
            .where(_CONFIDENCE_RAW == group.confidence_raw)  # noqa: SIM300
            .values(severity=group.severity)
        )
        updated += result.rowcount or 0
    session.commit()
    return updated
