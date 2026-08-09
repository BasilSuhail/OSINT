"""Batch pass — upgrade keyword-graded news rows to LLM verdicts (#591).

Never on the ingest path. Fetchers write `keyword_verdict` at ingest, which is
fast and cannot fail; this walks stored rows afterwards and replaces what it can.
A model outage therefore costs accuracy, never ingestion.

Rows already carrying an LLM verdict are skipped, so re-running is cheap and
idempotent.

    uv run python -m app.severity.grade_run --limit 200      # report
    uv run python -m app.severity.grade_run --limit 200 --apply
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import JSON, and_, bindparam, cast, func, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.brain import client
from app.db import session_scope
from app.db_models import EventRow
from app.settings import settings
from app.severity import news

logger = logging.getLogger(__name__)


#: The stored grader stamp, as a SQL expression. `as_string()` renders to
#: `->>` on Postgres and `json_extract` on SQLite, so the filter is portable
#: between production and the test suite.
_STORED_METHOD = EventRow.payload["severity_method"].as_string()

#: A guard rejection keeps the fallback severity, but it is still a completed
#: attempt for this model protocol. Stamping the method lets the fair queue move
#: past the row while a future method version can try it again.
ATTEMPTED_METHOD_KEY: str = "severity_grade_attempted_method"
ATTEMPTED_INPUT_KEY: str = "severity_grade_attempted_title"
COMPLETED_AT_KEY: str = "severity_grade_completed_at"
_STORED_ATTEMPTED_METHOD = EventRow.payload[ATTEMPTED_METHOD_KEY].as_string()
_STORED_ATTEMPTED_INPUT = EventRow.payload[ATTEMPTED_INPUT_KEY].as_string()
_STORED_ATTEMPTED_AT = EventRow.payload["severity_grade_attempted_at"].as_string()
_STORED_COMPLETED_AT = EventRow.payload[COMPLETED_AT_KEY].as_string()
_STORED_INPUT = func.coalesce(EventRow.payload["title"].as_string(), "")
_REJECTION_PAYLOAD_KEYS: tuple[str, ...] = (
    ATTEMPTED_METHOD_KEY,
    ATTEMPTED_INPUT_KEY,
    "severity_grade_attempted_at",
    "severity_grade_status",
)


def _is_pending() -> ColumnElement[bool]:
    """Rows neither graded nor rejected for their current input and method."""
    return and_(
        or_(_STORED_METHOD.is_(None), _STORED_METHOD != news.METHOD),
        or_(
            _STORED_ATTEMPTED_METHOD.is_(None),
            _STORED_ATTEMPTED_METHOD != news.METHOD,
            _STORED_ATTEMPTED_INPUT.is_(None),
            _STORED_ATTEMPTED_INPUT != _STORED_INPUT,
        ),
    )


def _input_title(row: EventRow) -> str:
    return str((row.payload or {}).get("title") or "")


def _merge_payload(
    session: Session, patch: dict, *, remove_keys: tuple[str, ...] = ()
) -> ColumnElement[dict]:
    """Atomic shallow payload merge for the active database dialect."""
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        base = EventRow.payload
        for key in remove_keys:
            base = base.op("-")(key)
        return base.op("||")(cast(patch, JSONB))
    sqlite_patch = {**patch, **{key: None for key in remove_keys}}
    return func.json_patch(EventRow.payload, bindparam(None, sqlite_patch, type_=JSON))


def mark_rejected(session: Session, row: EventRow, *, expected_title: str | None = None) -> bool:
    """Atomically stamp a rejection if the model input is still current."""
    title = _input_title(row) if expected_title is None else expected_title
    patch = {
        ATTEMPTED_METHOD_KEY: news.METHOD,
        ATTEMPTED_INPUT_KEY: title,
        "severity_grade_attempted_at": datetime.now(UTC).isoformat(),
        "severity_grade_status": "rejected",
    }
    result = session.execute(
        update(EventRow)
        .where(
            EventRow.id == row.id,
            func.coalesce(EventRow.payload["title"].as_string(), "") == title,
        )
        .values(payload=_merge_payload(session, patch))
        .returning(EventRow.id)
    ).scalar_one_or_none()
    if result is not None:
        session.refresh(row, ["payload"])
    return result is not None


def apply_grade(
    session: Session,
    row: EventRow,
    *,
    value: float,
    payload: dict,
    expected_title: str | None = None,
) -> bool:
    """Atomically store a grade if the model input is still current."""
    title = _input_title(row) if expected_title is None else expected_title
    completed_payload = {
        **payload,
        COMPLETED_AT_KEY: datetime.now(UTC).isoformat(),
    }
    result = session.execute(
        update(EventRow)
        .where(
            EventRow.id == row.id,
            func.coalesce(EventRow.payload["title"].as_string(), "") == title,
        )
        .values(
            severity=value,
            payload=_merge_payload(session, completed_payload, remove_keys=_REJECTION_PAYLOAD_KEYS),
        )
        .returning(EventRow.id)
    ).scalar_one_or_none()
    if result is not None:
        session.refresh(row, ["severity", "payload"])
    return result is not None


def pending(session: Session, *, limit: int) -> list[EventRow]:
    """RSS rows not yet graded by the model, fairly bounded by source.

    The already-graded filter runs in SQL, so `limit` bounds what the database
    returns. It used to over-fetch `limit * 4` rows and drop the graded ones in
    Python, which meant a whole-table regrade loaded every news row as an ORM
    object and held it for the entire run — 3.4 GB measured on the #597 pass,
    and more than a Pi has to give.

    A global newest-first queue let high-volume publishers occupy every small
    scheduled batch while quieter feeds remained on the keyword fallback.
    Pending rank is the first ordering key, so every source's oldest candidate
    is considered before any source's second. Last-served time rotates ties when
    there are more sources than slots: omitted sources keep an older timestamp
    and move ahead on the next tick. The oldest ordering inside each source also
    protects backlog rows from reaching the 30-day retention boundary.

    `payload` has no key at all on rows the model never touched, so the null
    case is spelled out rather than left to `!=`, which is never true against
    SQL NULL. Only `rss-*` rows belong to this headline protocol; other sources
    can legitimately use the `news` category without being model-grading work.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    ranked = (
        select(
            EventRow.id.label("event_id"),
            func.row_number()
            .over(
                partition_by=EventRow.source,
                order_by=(EventRow.occurred_at.asc(), EventRow.id.asc()),
            )
            .label("source_rank"),
        )
        .where(
            EventRow.source.like("rss-%"),
            _is_pending(),
        )
        .subquery()
    )
    source_progress = (
        select(
            EventRow.source.label("source"),
            func.max(func.coalesce(_STORED_COMPLETED_AT, _STORED_ATTEMPTED_AT)).label(
                "last_served"
            ),
        )
        .where(
            EventRow.source.like("rss-%"),
        )
        .group_by(EventRow.source)
        .subquery()
    )
    return list(
        session.execute(
            select(EventRow)
            .join(ranked, ranked.c.event_id == EventRow.id)
            .outerjoin(source_progress, source_progress.c.source == EventRow.source)
            .order_by(
                ranked.c.source_rank.asc(),
                source_progress.c.last_served.asc().nulls_first(),
                EventRow.occurred_at.asc(),
                EventRow.id.asc(),
            )
            .limit(limit)
        ).scalars()
    )


def pending_count(session: Session) -> int:
    """How many RSS rows are still ungraded, table-wide.

    `pending` is bounded by `limit`, so it answers "what is in this batch",
    never "is the table done". The run's closing line needs the second
    question answered or a completed batch reads as a completed job (#644).
    """
    return int(
        session.execute(
            select(func.count())
            .select_from(EventRow)
            .where(
                EventRow.source.like("rss-%"),
                _is_pending(),
            )
        ).scalar_one()
    )


def grade_row(row: EventRow, *, model: str) -> tuple[float, dict] | None:
    """Ask the model, run every guard, return (severity, payload) or None."""
    headline = (row.payload or {}).get("title") or ""
    if not headline:
        return None
    # keep_alive keeps the model resident across the batch; reloading a 4B per
    # row dominates the runtime otherwise.
    payload = client.generate_json(news.build_prompt(headline), model=model, keep_alive="5m")
    verdict = news.verdict_from_payload(payload, headline=headline)
    if verdict is None:
        return None
    return verdict.value, verdict.as_payload()


#: Rows per commit. A regrade of the whole news table is ~13h of model calls;
#: committing once at the end made it a single transaction that saved nothing if
#: interrupted (#596). Committing in batches also makes the run resumable —
#: `pending` already skips rows carrying the LLM method, so a re-run picks up
#: exactly where a killed one stopped.
COMMIT_EVERY: int = 50


def _grade_batch(
    session: Session,
    rows: list[EventRow],
    *,
    model: str,
    apply: bool,
    grade: Callable[..., tuple[float, dict] | None],
) -> tuple[int, int]:
    """Grade one snapshot of rows. Returns (graded, skipped)."""
    graded = skipped = 0
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        input_title = _input_title(row)
        result = grade(row, model=model)
        if result is None:
            skipped += 1
            if apply:
                mark_rejected(session, row, expected_title=input_title)
            continue
        value, payload = result
        before = row.severity
        print(
            f"  [{index}/{total}] {before} -> {value}  {payload['severity_band']:<14} "
            f"{(row.payload or {}).get('title', '')[:60]}"
        )
        print(f"      {payload['severity_rationale']}")
        if apply:
            if not apply_grade(
                session, row, value=value, payload=payload, expected_title=input_title
            ):
                skipped += 1
                continue
            # Commit as we go so a 13h run is never one all-or-nothing
            # transaction, and a kill costs at most COMMIT_EVERY rows (#596).
            if graded % COMMIT_EVERY == 0:
                session.commit()
        graded += 1
    if apply:
        session.commit()
    return graded, skipped


def run(
    session: Session,
    *,
    limit: int,
    model: str,
    apply: bool,
    until_empty: bool,
    grade: Callable[..., tuple[float, dict] | None] = grade_row,
) -> tuple[int, int]:
    """Grade one batch, or keep re-snapshotting until the table is drained.

    A single batch is what the runner always did, and it is why every long
    run ended looking stuck: `pending` snapshots once, ingest keeps arriving,
    so the 30h #597 pass finished its 17,489 rows with ~2,000 newer ones
    behind it and no hint of them in the log (#644).

    `until_empty` re-snapshots after each batch. Re-snapshotting is safe
    because `pending` already excludes graded rows (#596), so a pass never
    redoes work. It stops when the table is empty or when a whole pass grades
    nothing — a row that always fails a guard stays pending forever, and
    without the progress check it would spin on that row indefinitely.
    """
    graded = skipped = 0
    while True:
        rows = pending(session, limit=limit)
        if not rows:
            break
        print(f"{len(rows)} ungraded RSS row(s) this pass\n")
        pass_graded, pass_skipped = _grade_batch(
            session, rows, model=model, apply=apply, grade=grade
        )
        graded += pass_graded
        skipped += pass_skipped
        # Release the pass's ORM objects: holding every row of a whole-table
        # regrade cost 3.4 GB before #596's bounded fetch, and a drain loop
        # would accumulate the same way across passes.
        session.expunge_all()
        # A dry run never changes the pending set, so draining would repeat the
        # same page forever. Applied rejections are terminal attempts and count
        # as progress even though they preserve the fallback severity.
        if not until_empty or not apply or pass_graded + pass_skipped == 0:
            break
    return graded, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true", help="write the graded verdicts")
    parser.add_argument("--model", default=settings.severity_model)
    parser.add_argument(
        "--until-empty",
        action="store_true",
        help="keep re-snapshotting until no ungraded news rows remain",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    with session_scope() as session:
        graded, skipped = run(
            session,
            limit=args.limit,
            model=args.model,
            apply=args.apply,
            until_empty=args.until_empty,
        )
        remaining = pending_count(session)

    print(f"\n{graded} graded, {skipped} rejected by a guard or unparseable.")
    # State the table, not the batch: a finished batch is not a finished job,
    # and the log is what a human reads to tell the difference (#644).
    print(f"{remaining} RSS row(s) still ungraded.")
    if not args.apply:
        print("dry run — nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
