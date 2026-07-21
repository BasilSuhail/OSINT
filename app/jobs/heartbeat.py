"""Heartbeat records for long-running jobs (#341).

Every one-shot entrypoint (backfills, exports) and analytical beat body wraps
itself in `job_run(name)`: a `job_runs` row is inserted at start, the heartbeat
advances while the job lives, and the row is closed as done/failed on exit.
Each write uses its own short-lived session so progress is visible from the API
mid-run.

The API's rule is "running with a heartbeat older than ~10 minutes means the
process died". Two things are needed to make that true, and neither was there
(#564):

**A live job must prove it is alive.** `progress()` was the only thing that
advanced the heartbeat, and exactly one of fifteen call sites ever called it —
so a healthy job running longer than the threshold was reported as a corpse. A
background thread now bumps the heartbeat on its own; `progress()` remains for
publishing a human-readable line, not for staying alive.

**A dead job must stop looking alive.** Exceptions mark the row failed, but a
process killed without unwinding never reaches that code — SIGTERM, which is
what ``scripts/dev-down.sh`` sends, does not raise in Python. Such a row stayed
`running` forever with nothing recorded. Starting a job now reconciles
abandoned runs of the same job, so the failure becomes visible on the next run
rather than never.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, update
from sqlalchemy.orm import Session, sessionmaker

from app.db_models import JobRunRow
from app.settings import settings

#: Completed runs older than this are deleted on the next job start — cheap
#: housekeeping so the beat jobs (48 runs/day) never accumulate unbounded.
RETENTION_DAYS = 14

#: Error detail is truncated to keep the row (and the chip tooltip) sane.
DETAIL_MAX_CHARS = 500

#: How often a live job bumps its heartbeat. Comfortably under the API's
#: ~10-minute staleness rule, and cheap: one tiny UPDATE per minute per job.
HEARTBEAT_INTERVAL_S = 60.0

#: How stale a `running` row must be before a later run of the same job
#: declares it abandoned. Well past the bump interval so a live job is never
#: killed off by a concurrent one starting.
ABANDONED_AFTER = timedelta(minutes=30)

ABANDONED_DETAIL = (
    "abandoned: no heartbeat for over {minutes} minutes and a later run started. "
    "The process was killed without unwinding (SIGTERM/SIGKILL, an OOM kill or a "
    "container stop), so it could not record its own failure."
)

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


def _reap_abandoned(session: Session, job: str, now: datetime) -> None:
    """Close rows for `job` left `running` by a process that never unwound.

    Scoped to the one job so an unrelated stuck run is not attributed to
    whatever happens to start next, and bounded by staleness so a genuinely
    live concurrent run is untouched.
    """
    cutoff = now - ABANDONED_AFTER
    session.execute(
        update(JobRunRow)
        .where(
            JobRunRow.job == job,
            JobRunRow.status == "running",
            JobRunRow.finished_at.is_(None),
            JobRunRow.heartbeat_at < cutoff,
        )
        .values(
            status="failed",
            finished_at=now,
            detail=ABANDONED_DETAIL.format(minutes=int(ABANDONED_AFTER.total_seconds() // 60)),
        )
    )


@contextmanager
def job_run(
    job: str,
    *,
    session_factory: SessionFactory | None = None,
    evict_brain: bool = True,
    heartbeat_interval_s: float = HEARTBEAT_INTERVAL_S,
) -> Iterator[Callable[[str], None]]:
    """Record one job execution; yields a `progress(text)` heartbeat function.

    Exceptions mark the row failed (with truncated detail) and re-raise —
    the job's own error handling stays untouched.

    On start, best-effort evicts the brain model (#409) so a heavy job
    reclaims its RAM before the work begins. The brain's own narrate task
    passes ``evict_brain=False`` so it never evicts itself.
    """
    if evict_brain and settings.brain_enabled:
        try:
            from app.brain.client import evict

            evict()
        except Exception:  # best-effort: the brain must never break a real job
            pass

    factory = session_factory or _default_factory()

    def _start(session: Session) -> int:
        now = datetime.now(UTC)
        session.execute(
            delete(JobRunRow).where(
                JobRunRow.finished_at.is_not(None),
                JobRunRow.started_at < now - timedelta(days=RETENTION_DAYS),
            )
        )
        _reap_abandoned(session, job, now)
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

    def _touch() -> None:
        now = datetime.now(UTC)

        def _bump(session: Session) -> None:
            session.query(JobRunRow).filter_by(id=run_id).update({"heartbeat_at": now})

        _write(factory, _bump)

    #: Liveness is the thread's job, not the call site's. A daemon thread so a
    #: hung job can never keep the interpreter alive on its own.
    stop = threading.Event()

    def _beat() -> None:
        while not stop.wait(heartbeat_interval_s):
            # A bookkeeping write must never kill a real job.
            with contextlib.suppress(Exception):
                _touch()

    beater = threading.Thread(target=_beat, name=f"heartbeat-{job}", daemon=True)
    beater.start()

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
    finally:
        stop.set()
        beater.join(timeout=heartbeat_interval_s)
