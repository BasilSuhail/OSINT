"""Ingest watchdog.

Walks ``ingest_health`` once per beat fire and flags sources whose last
successful fetch is older than ``cadence x STALE_MULTIPLIER`` minutes. A
flagged source produces:

1. A row in ``notifications`` (so the frontend ConnectionIndicator can show it)
2. A Pushover message if ``PUSHOVER_TOKEN`` + ``PUSHOVER_USER`` are configured
3. A WARNING log line regardless of Pushover state

Dedup: the ``notifications.dedup_key`` UNIQUE index keeps us from re-paging the
same source more than once per day. Reset happens automatically as a new UTC
day rolls in.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db_models import EventRow, IngestHealthRow, JobRunRow, NotificationRow
from app.settings import settings
from app.sources.rss_registry import feed_cadence_map

logger = logging.getLogger(__name__)


#: Polling cadence in minutes per source. Mirrors the beat schedule in
#: ``app/tasks.py``. Editing one without the other is a bug.
CORE_SOURCE_CADENCE_MIN: dict[str, int] = {
    "yfinance": 5,
    "fred": 1440,  # daily
    "gdelt": 15,
    "acled": 60,
    "emdat": 1440,
    "usgs-quake": 15,
    "gdacs": 15,
    "nasa-firms": 60,
    "eonet": 30,
    "uk-police": 1440,
    "opensky-adsb": 60,
    "abuse-ch-urlhaus": 15,
    "abuse-ch-feodo": 15,
    "polymarket": 30,
}

SOURCE_CADENCE_MIN: dict[str, int] = {
    **CORE_SOURCE_CADENCE_MIN,
    **feed_cadence_map(),
}

#: A source is "stale" once last_success is older than this many cadence
#: windows. With STALE_MULTIPLIER=6, a 15-min fetcher is flagged after 90 min
#: of silence — enough headroom that one missed beat doesn't trip the alarm,
#: tight enough that a real outage pages within an hour.
STALE_MULTIPLIER: int = 6


def _last_success(session: Session, source: str) -> datetime | None:
    """Return the most recent ``last_success`` across the per-day rows for ``source``.

    SQLite drops tzinfo on round-trip, so we re-attach UTC if the driver hands
    back a naive datetime; Postgres returns tz-aware values directly.
    """
    stmt = (
        select(IngestHealthRow.last_success)
        .where(IngestHealthRow.source == source)
        .where(IngestHealthRow.last_success.is_not(None))
        .order_by(IngestHealthRow.day.desc())
        .limit(1)
    )
    row = session.execute(stmt).first()
    if row is None:
        return None
    value = row[0]
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def _pushover_send(message: str) -> None:
    """Best-effort Pushover notification. Silent if credentials missing."""
    if not settings.pushover_token or not settings.pushover_user:
        return
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": settings.pushover_token,
                    "user": settings.pushover_user,
                    "title": "OSINT ingest watchdog",
                    "message": message,
                },
            )
    except httpx.HTTPError as exc:
        logger.warning("watchdog: pushover send failed: %s", exc)


def _persist_notification(
    session: Session, *, source: str, message: str, today: date, kind: str = "stale"
) -> bool:
    """Insert a notifications row; return True if a new row was inserted."""
    dedup_key = f"watchdog:{kind}:{source}:{today.isoformat()}"
    row = {
        "channel": "watchdog",
        "country": None,
        "score_value": None,
        "message": message,
        "dedup_key": dedup_key,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        stmt = (
            pg_insert(NotificationRow)
            .values(row)
            .on_conflict_do_nothing(index_elements=["dedup_key"])
            .returning(NotificationRow.id)
        )
    elif dialect == "sqlite":
        stmt = (
            sqlite_insert(NotificationRow)
            .values(row)
            .on_conflict_do_nothing(index_elements=["dedup_key"])
            .returning(NotificationRow.id)
        )
    else:
        raise NotImplementedError(f"watchdog does not support dialect {dialect!r}")
    result = session.execute(stmt)
    return result.first() is not None


def check_sources(session: Session, *, now: datetime | None = None) -> dict[str, dict[str, object]]:
    """Run one watchdog sweep over every source. Return per-source state."""
    now = now or datetime.now(UTC)
    today = now.date()
    report: dict[str, dict[str, object]] = {}

    for source, cadence_min in SOURCE_CADENCE_MIN.items():
        threshold = timedelta(minutes=cadence_min * STALE_MULTIPLIER)
        last_success = _last_success(session, source)
        is_stale = last_success is None or (now - last_success) > threshold

        report[source] = {
            "last_success": last_success,
            "is_stale": is_stale,
            "alerted": False,
        }

        if not is_stale:
            continue

        if last_success is None:
            message = f"{source}: no successful fetch on record (cadence {cadence_min} min)"
        else:
            age_min = int((now - last_success).total_seconds() / 60)
            message = (
                f"{source}: last_success {age_min} min ago "
                f"(cadence {cadence_min} min x {STALE_MULTIPLIER} = stale)"
            )

        logger.warning("watchdog: %s", message)
        if _persist_notification(session, source=source, message=message, today=today):
            _pushover_send(message)
            report[source]["alerted"] = True

    return report


#: Hazard footprint coverage watchdog (#617). Ingest health only proves a fetch
#: succeeded — GDACS answered perfectly all through #604 while every refresh
#: deleted the geometry the map needed. This watches the OUTPUT instead.
FOOTPRINT_SOURCE: str = "gdacs"
#: Rows younger than this have not been through the enrichment beat yet.
FOOTPRINT_GRACE_MIN: int = 60
#: Below this share of eligible rows carrying geometry, something is wrong:
#: the refresh path, the GDACS geometry endpoint, or the enrichment task.
FOOTPRINT_MIN_COVERAGE: float = 0.6
#: Too few rows to conclude anything — right after a wipe, or a quiet feed.
FOOTPRINT_MIN_SAMPLE: int = 20


def check_footprint_coverage(session: Session, *, now: datetime | None = None) -> dict[str, object]:
    """Flag a collapse in the share of hazards carrying real footprint geometry.

    Eligible rows are GDACS hazards old enough to have been enriched and not
    already stamped ``footprint_checked_at`` — that stamp means upstream has no
    geometry for them, which is normal and must not drag the ratio down or the
    alarm would ring forever.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(minutes=FOOTPRINT_GRACE_MIN)
    payload = EventRow.payload
    eligible_rows = (
        select(payload["footprint_geojson"].as_string())
        .where(EventRow.source == FOOTPRINT_SOURCE)
        .where(EventRow.fetched_at <= cutoff)
        .where(payload["footprint_checked_at"].as_string().is_(None))
    )
    geojson = [row[0] for row in session.execute(eligible_rows).all()]
    eligible = len(geojson)
    with_geometry = sum(1 for value in geojson if value is not None)
    coverage = with_geometry / eligible if eligible else 1.0

    report: dict[str, object] = {
        "eligible": eligible,
        "with_geometry": with_geometry,
        "coverage": coverage,
        "alerted": False,
    }
    if eligible < FOOTPRINT_MIN_SAMPLE or coverage >= FOOTPRINT_MIN_COVERAGE:
        return report

    message = (
        f"{FOOTPRINT_SOURCE}: footprint coverage {with_geometry}/{eligible} "
        f"({coverage:.0%}) below {FOOTPRINT_MIN_COVERAGE:.0%} — hazards are drawing "
        f"synthesized circles instead of real geometry"
    )
    logger.warning("watchdog: %s", message)
    if _persist_notification(
        session, source=FOOTPRINT_SOURCE, message=message, today=now.date(), kind="footprint"
    ):
        _pushover_send(message)
        report["alerted"] = True
    return report


#: Job-failure watchdog (#657). `sensor-checks` failed 717 times in 24 hours
#: (#656) and nothing said a word — the reaper from #564 recorded every one of
#: them faithfully, but recording a failure is not reporting one, and nobody
#: reads `job_runs` unprompted. Ingest health was green throughout: the sensors
#: kept arriving perfectly, and the job that reads them was dead.
#:
#: Cadence in minutes per scheduled job, mirroring `beat_schedule` in
#: ``app/tasks.py``. Editing one without the other is a bug — same contract as
#: ``CORE_SOURCE_CADENCE_MIN`` above.
#:
#: One-shot entrypoints (`backfill-signals`, `panel`, `baselines`, `labels`,
#: `coverage`, `onset-eval`, `within-eval`, `indicator-ranking`) are absent on
#: purpose. They legitimately go months without running and must never page.
JOB_CADENCE_MIN: dict[str, int] = {
    "brain-narrate": 15,
    "brain-enrich": 20,
    "stories-cluster": 30,
    "sensor-checks": 30,
    "disagreement": 30,
    "severity-grade": 30,
    "journal": 1440,
    "validator": 1440,
    "briefing": 10080,
}

#: A job is stale after this many of its own cadences without a `done` run.
JOB_STALE_MULTIPLIER: int = 3

#: Ceiling on the extra grace a long-cadence job gets. Without it a weekly
#: briefing would need to be missed for three weeks before anyone heard, since
#: three cadences of a weekly job is most of a month.
JOB_MAX_GRACE_MIN: int = 1440

#: Runs inspected when judging whether a job is failing rather than merely
#: quiet. Wide enough to survive one bad run, short enough to notice a job that
#: has started failing every time.
JOB_RECENT_RUNS: int = 10

#: Above this share of failures among recent runs, a job is broken even if it
#: occasionally squeaks out a success and never looks stale.
JOB_MAX_FAILURE_RATE: float = 0.5


def job_stale_after(cadence_min: int) -> timedelta:
    """How long a job may go without a `done` run before it is stale.

    Its cadence tripled, but never more than a day of extra grace on top.
    """
    tripled = cadence_min * JOB_STALE_MULTIPLIER
    return timedelta(minutes=min(tripled, cadence_min + JOB_MAX_GRACE_MIN))


def _last_done(session: Session, job: str) -> datetime | None:
    """When this job last finished successfully.

    Re-attaches UTC on a naive value for the same reason `_last_success` does:
    SQLite drops tzinfo on round-trip, Postgres does not.
    """
    stmt = (
        select(JobRunRow.finished_at)
        .where(JobRunRow.job == job, JobRunRow.status == "done")
        .order_by(JobRunRow.finished_at.desc())
        .limit(1)
    )
    value = session.execute(stmt).scalars().first()
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def _recent_failure_rate(session: Session, job: str) -> tuple[int, int, str | None]:
    """(failed, considered, last failure detail) over the most recent runs.

    `running` rows are excluded rather than counted either way: a job in flight
    has not succeeded or failed yet, and #564's reaper will close it out on the
    next start if the process died.
    """
    stmt = (
        select(JobRunRow.status, JobRunRow.detail)
        .where(JobRunRow.job == job, JobRunRow.status.in_(("done", "failed")))
        .order_by(JobRunRow.started_at.desc())
        .limit(JOB_RECENT_RUNS)
    )
    rows = session.execute(stmt).all()
    failed = [row for row in rows if row.status == "failed"]
    detail = next((row.detail for row in failed if row.detail), None)
    return len(failed), len(rows), detail


def check_jobs(session: Session, *, now: datetime | None = None) -> dict[str, dict[str, object]]:
    """Flag scheduled jobs that have stopped succeeding. Return per-job state.

    Two signals, because a job can break in two shapes. It can go quiet — the
    #656 case, where the worker was killed before it could finish anything. Or
    it can keep running and keep failing, staying just fresh enough never to
    look stale. Both mean the same thing to whoever depends on the output.

    A job doing nothing is not a job that is broken: `severity-grade` returning
    `considered: 0` because there is no backlog is a success, and the beat
    bodies that skip on a busy box return before opening a run at all. This
    reads run outcomes, never the work they did.
    """
    now = now or datetime.now(UTC)
    today = now.date()
    report: dict[str, dict[str, object]] = {}

    for job, cadence_min in JOB_CADENCE_MIN.items():
        threshold = job_stale_after(cadence_min)
        last_done = _last_done(session, job)
        failed, considered, detail = _recent_failure_rate(session, job)

        is_stale = last_done is None or (now - last_done) > threshold
        is_failing = considered > 0 and (failed / considered) > JOB_MAX_FAILURE_RATE

        report[job] = {
            "last_done": last_done,
            "is_stale": is_stale,
            "is_failing": is_failing,
            "failed_recent": failed,
            "considered_recent": considered,
            "alerted": False,
        }

        if not (is_stale or is_failing):
            continue
        if last_done is None and considered == 0:
            # Never run at all. On a fresh database that is every job, and a
            # page per job on first boot is noise, not signal.
            continue

        if is_stale and last_done is not None:
            age_min = int((now - last_done).total_seconds() / 60)
            headline = (
                f"{job}: no successful run for {age_min} min "
                f"(cadence {cadence_min} min, stale after {int(threshold.total_seconds() / 60)})"
            )
        elif is_stale:
            headline = f"{job}: no successful run on record (cadence {cadence_min} min)"
        else:
            headline = (
                f"{job}: {failed} of the last {considered} runs failed (cadence {cadence_min} min)"
            )

        # The reaper's detail already explains the cause — an OOM kill reads as
        # "abandoned: no heartbeat ... killed without unwinding". Quoting it
        # makes the page actionable instead of just alarming.
        message = f"{headline} — last failure: {detail}" if detail else headline

        logger.warning("watchdog: %s", message)
        if _persist_notification(session, source=job, message=message, today=today, kind="job"):
            _pushover_send(message)
            report[job]["alerted"] = True

    return report
