"""Re-derive stored FIRMS severity from FRP instead of confidence (#579).

Replaces the #577 confidence backfill, which is now deleted: that sweep wrote
the *right value of the wrong quantity*. Detection confidence answers "is this
pixel fire at all"; severity is read downstream as "how bad is this". On the
stored rows the two run non-monotonic — `l` pixels average 18.27 MW against
8.91 MW for `n` — so recovering more confidence-derived severities only spread
the inversion further.

Every FIRMS row is rewritten, not only the NULL ones. Rows swept by #577 hold a
confidence-derived value and are exactly the rows that must change.

Unlike #577 this cannot group by distinct value. Confidence took three values,
so half a million rows resolved to three UPDATEs; FRP is continuous, so the
work is batched by primary key instead — ~537 statements at the default batch
size, which is the price of the value being continuous at all.

Reporting and writing are separate calls, as in #577 and #553's gist sweep:
this mutates rows the composite reads, so the counts are worth reading first.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from app.db_models import EventRow
from app.sources.nasa_firms_fetcher import NasaFirmsFetcher, frp_to_severity

#: JSON paths to the values the fetcher has always stored. Read via SQLAlchemy's
#: JSON accessor rather than `->>` so the same code runs against the SQLite the
#: unit suite uses and the Postgres used in anger.
_FRP = EventRow.payload["frp"].as_string()
_CONFIDENCE_RAW = EventRow.payload["confidence_raw"].as_string()

#: Rows per UPDATE. Large enough that half a million rows is a few hundred
#: statements, small enough that one statement is not a long-held write lock on
#: a table the fetchers are still inserting into.
DEFAULT_BATCH_SIZE: int = 1_000


@dataclass(frozen=True)
class ResweepPlan:
    """What a resweep would do. Produced without writing anything."""

    #: Rows that resolve to a severity under the FRP derivation.
    rewritable_rows: int = 0
    #: Rows whose stored FRP or confidence cannot be read, so they end up with
    #: no severity. Reported rather than silently skipped: if a future FIRMS
    #: product drops the `frp` column this number is how it becomes visible,
    #: which is the failure mode #574 spent the source's whole life hiding.
    unreadable_rows: int = 0
    #: Rows already holding the value the derivation would write. A second run
    #: reports all of them here and writes nothing.
    unchanged_rows: int = 0

    @property
    def total_rows(self) -> int:
        return self.rewritable_rows + self.unreadable_rows + self.unchanged_rows


def _derive(frp: str | None, confidence_raw: str | None) -> float | None:
    return frp_to_severity(frp, confidence_raw=confidence_raw)


def plan_resweep(session: Session, *, source: str = NasaFirmsFetcher.name) -> ResweepPlan:
    """Count what the resweep would change. Writes nothing.

    Grouped by (frp, confidence_raw) rather than scanned row by row — distinct
    FRP values number in the thousands, not the hundreds of thousands, so the
    report costs one aggregate query instead of half a million round trips.
    """
    rows = session.execute(
        select(_FRP, _CONFIDENCE_RAW, EventRow.severity, func.count())
        .where(EventRow.source == source)
        .group_by(_FRP, _CONFIDENCE_RAW, EventRow.severity)
    ).all()

    rewritable = 0
    unreadable = 0
    unchanged = 0
    for frp, confidence_raw, severity, count in rows:
        derived = _derive(frp, confidence_raw)
        if derived is None:
            unreadable += count
        elif severity is not None and abs(float(severity) - derived) < 1e-9:
            unchanged += count
        else:
            rewritable += count
    return ResweepPlan(
        rewritable_rows=rewritable, unreadable_rows=unreadable, unchanged_rows=unchanged
    )


def apply_resweep(
    session: Session,
    *,
    source: str = NasaFirmsFetcher.name,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Rewrite every FIRMS severity from FRP. Returns rows actually changed.

    Walks the table by ascending primary key so a batch is a bounded range
    scan, and commits per batch: a resweep of half a million rows that dies
    two thirds through leaves two thirds done rather than nothing, and rerunning
    it is safe because the derivation is a pure function of stored values.

    Rows whose FRP cannot be read are set back to NULL rather than left holding
    the old confidence-derived number. A stale value from a superseded method is
    worse than an absent one — the composite skips NULL, but it would happily
    score the stale one.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    changed = 0
    last_id = 0
    while True:
        batch = session.execute(
            select(EventRow.id, _FRP, _CONFIDENCE_RAW, EventRow.severity)
            .where(EventRow.source == source)
            .where(EventRow.id > last_id)
            .order_by(EventRow.id)
            .limit(batch_size)
        ).all()
        if not batch:
            break
        last_id = batch[-1][0]

        # One UPDATE per batch via CASE, rather than one per row: the same
        # write, two orders of magnitude fewer round trips.
        updates: dict[int, float | None] = {}
        for row_id, frp, confidence_raw, severity in batch:
            derived = _derive(frp, confidence_raw)
            if derived is None and severity is None:
                continue
            if (
                derived is not None
                and severity is not None
                and abs(float(severity) - derived) < 1e-9
            ):
                continue
            updates[row_id] = derived

        # Rows losing their severity are a separate, simpler statement — a CASE
        # carrying NULL branches is harder to read than it is worth.
        clearing = [row_id for row_id, value in updates.items() if value is None]
        setting = {row_id: value for row_id, value in updates.items() if value is not None}

        if clearing:
            session.execute(update(EventRow).where(EventRow.id.in_(clearing)).values(severity=None))
            changed += len(clearing)
        if setting:
            session.execute(
                update(EventRow)
                .where(EventRow.id.in_(list(setting)))
                .values(severity=case(setting, value=EventRow.id))
            )
            changed += len(setting)
        session.commit()

    return changed
