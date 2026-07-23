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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brain import client
from app.db import session_scope
from app.db_models import EventRow
from app.models import Category
from app.settings import settings
from app.severity import news

logger = logging.getLogger(__name__)


def pending(session: Session, *, limit: int) -> list[EventRow]:
    """News rows not yet graded by the model, newest first."""
    rows = session.execute(
        select(EventRow)
        .where(EventRow.category == Category.NEWS.value)
        .order_by(EventRow.occurred_at.desc())
        .limit(limit * 4)
    ).scalars()
    out = []
    for row in rows:
        if (row.payload or {}).get("severity_method") == news.METHOD:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true", help="write the graded verdicts")
    parser.add_argument("--model", default=settings.ollama_model)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    graded = skipped = 0
    with session_scope() as session:
        rows = pending(session, limit=args.limit)
        total = len(rows)
        print(f"{total} ungraded news row(s)\n")
        for index, row in enumerate(rows, start=1):
            result = grade_row(row, model=args.model)
            if result is None:
                skipped += 1
                continue
            value, payload = result
            before = row.severity
            print(
                f"  [{index}/{total}] {before} -> {value}  {payload['severity_band']:<14} "
                f"{(row.payload or {}).get('title', '')[:60]}"
            )
            print(f"      {payload['severity_rationale']}")
            if args.apply:
                row.severity = value
                row.payload = {**(row.payload or {}), **payload}
                # Commit as we go so a 13h run is never one all-or-nothing
                # transaction, and a kill costs at most COMMIT_EVERY rows (#596).
                if graded % COMMIT_EVERY == 0:
                    session.commit()
            graded += 1
        if args.apply:
            session.commit()

    print(f"\n{graded} graded, {skipped} rejected by a guard or unparseable.")
    if not args.apply:
        print("dry run — nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
