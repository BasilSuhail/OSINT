"""Heartbeat records for long-running jobs (#341).

Every one-shot entrypoint (backfills, exports) and analytical beat body wraps
itself in `job_run(name)`: a `job_runs` row is inserted at start, `progress()`
bumps the heartbeat with a human-readable line, and the row is closed as
done/failed on exit. Each write uses its own short-lived session so progress
is visible from the API mid-run and a crashed job leaves its row `running`
with a stale heartbeat — which is exactly the signal the top bar needs to
show "stalled".
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from app.db_models import JobRunRow

#: Completed runs older than this are deleted on the next job start — cheap
#: housekeeping so the beat jobs (48 runs/day) never accumulate unbounded.
RETENTION_DAYS = 14

#: Error detail is truncated to keep the row (and the chip tooltip) sane.
DETAIL_MAX_CHARS = 500

SessionFactory = Callable[[], Session]


def _default_factory() -> sessionmaker[Session]:
    from app.db import get_session_factory

    return get_session_factory()


def _write(factory: SessionFactory, fn: Callable[[Session], object]) -> object:
    session = factory()
    try:
        result = fn(session)
        session.commit()
        return result
    finally:
        session.close()


@contextmanager
def job_run(
    job: str, *, session_factory: SessionFactory | None = None
) -> Iterator[Callable[[str], None]]:
    """Record one job execution; yields a `progress(text)` heartbeat function.

    Exceptions mark the row failed (with truncated detail) and re-raise —
    the job's own error handling stays untouched.
    """
    factory = session_factory or _default_factory()

    def _start(session: Session) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
        session.execute(
            delete(JobRunRow).where(
                JobRunRow.finished_at.is_not(None), JobRunRow.started_at < cutoff
            )
        )
        row = JobRunRow(job=job, status="running")
        session.add(row)
        session.flush()
        return row.id

    run_id = _write(factory, _start)

    def progress(text: str) -> None:
        now = datetime.now(UTC)

        def _bump(session: Session) -> None:
            session.query(JobRunRow).filter_by(id=run_id).update(
                {"progress": text, "heartbeat_at": now}
            )

        _write(factory, _bump)

    def _finish(status: str, detail: str | None) -> None:
        now = datetime.now(UTC)

        def _close(session: Session) -> None:
            session.query(JobRunRow).filter_by(id=run_id).update(
                {
                    "status": status,
                    "detail": detail,
                    "finished_at": now,
                    "heartbeat_at": now,
                }
            )

        _write(factory, _close)

    try:
        yield progress
    except BaseException as error:
        _finish("failed", str(error)[:DETAIL_MAX_CHARS] or type(error).__name__)
        raise
    else:
        _finish("done", None)
