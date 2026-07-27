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
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.db_models import (
    BrainNarrativeRow,
    EventRow,
    IngestHealthRow,
    JobRunRow,
    NotificationRow,
    StoryDisagreementRow,
    StoryGistRow,
    StoryRow,
    StorySensorCheckRow,
)
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


#: Output watchdog (#663). #659 watches whether jobs *run*; this watches whether
#: they *do anything*. The brain returned `done` 63 times in a day while
#: producing no narrative at all — every layer honest, every light green,
#: nothing wrong to find, because backing off is a success (#413). #630 and
#: #660 were the same shape. `check_footprint_coverage` above exists for the
#: same reason on the ingest side: watching input never sees output stop.
#:
#: job -> (what it writes, the column that advances when it works)
JOB_OUTPUT: dict[str, tuple[type, InstrumentedAttribute]] = {
    "brain-narrate": (BrainNarrativeRow, BrainNarrativeRow.created_at),
    "brain-enrich": (StoryGistRow, StoryGistRow.created_at),
    "sensor-checks": (StorySensorCheckRow, StorySensorCheckRow.checked_at),
    "disagreement": (StoryDisagreementRow, StoryDisagreementRow.computed_at),
    "stories-cluster": (StoryRow, StoryRow.last_seen),
}

#: `severity-grade` is deliberately absent, and this is the design decision of
#: the whole check rather than an oversight. Its backlog legitimately empties:
#: `{"considered": 0}` with nothing pending is correct, healthy and the normal
#: steady state since #631, so watching its output would page on success. Every
#: table above receives rows on every healthy pass — there is always a situation
#: to narrate, always new stories to gist, always stories in the clustering
#: window — so silence there really does mean something is wrong.

#: How many of its own cadences a job may produce nothing before it is flagged.
#: Deliberately looser than the failure check: these jobs skip on purpose when
#: the box is busy (#409), and an afternoon of real work must not page.
OUTPUT_STALE_MULTIPLIER: int = 8

#: Ceiling on the extra grace, as in `job_stale_after`.
OUTPUT_MAX_GRACE_MIN: int = 1440


def output_stale_after(cadence_min: int) -> timedelta:
    """How long a job may produce nothing before that is worth saying."""
    scaled = cadence_min * OUTPUT_STALE_MULTIPLIER
    return timedelta(minutes=min(scaled, cadence_min + OUTPUT_MAX_GRACE_MIN))


def _last_output(session: Session, column: InstrumentedAttribute) -> datetime | None:
    value = session.execute(select(func.max(column))).scalars().first()
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def _ran_since(session: Session, job: str, cutoff: datetime) -> bool:
    """Did this job actually complete a run inside the window?

    Without this the check pages after any downtime. The stack was off from
    01:15 to 10:32 on 2026-07-27, and the first sweep after restart would have
    seen a 556-minute gap in every output table and fired on all of them. That
    is not "succeeded while producing nothing" — it is "was not running", which
    is #657's question and is answered there. This check only speaks when the
    job demonstrably ran and still produced nothing.
    """
    stmt = (
        select(JobRunRow.id)
        .where(
            JobRunRow.job == job,
            JobRunRow.status == "done",
            JobRunRow.finished_at >= cutoff,
        )
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def _last_run_reason(session: Session, job: str) -> str | None:
    """What the job's most recent finished run recorded, if anything.

    A page saying "produced nothing for 6h" sends someone to psql. One that adds
    `low RAM: 1072MB free < 1200MB floor` is the diagnosis — the same reason
    `check_jobs` quotes the reaper's detail.
    """
    stmt = (
        select(JobRunRow.detail)
        .where(JobRunRow.job == job, JobRunRow.detail.is_not(None))
        .order_by(JobRunRow.started_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def check_output(session: Session, *, now: datetime | None = None) -> dict[str, dict[str, object]]:
    """Flag jobs whose output has stopped advancing. Return per-job state.

    Says nothing about quality — only whether anything came out. Whether what
    came out is any good is what the eval harnesses are for (#593, #432).
    """
    now = now or datetime.now(UTC)
    today = now.date()
    report: dict[str, dict[str, object]] = {}

    for job, (_, column) in JOB_OUTPUT.items():
        cadence_min = JOB_CADENCE_MIN[job]
        threshold = output_stale_after(cadence_min)
        last_output = _last_output(session, column)
        # Never produced anything at all: a fresh database is every job at once,
        # and paging on first boot is how a channel gets ignored.
        no_output = last_output is not None and (now - last_output) > threshold
        # ...and it only counts if the job ran during that silence. Otherwise
        # this fires on every restart after a night with the stack off.
        ran = _ran_since(session, job, now - threshold)
        is_stale = no_output and ran

        report[job] = {
            "last_output": last_output,
            "ran_in_window": ran,
            "is_stale": is_stale,
            "alerted": False,
        }
        if not is_stale:
            continue

        age_min = int((now - last_output).total_seconds() / 60)
        headline = (
            f"{job}: ran, but produced nothing for {age_min} min "
            f"(cadence {cadence_min} min, expected output within "
            f"{int(threshold.total_seconds() / 60)})"
        )
        reason = _last_run_reason(session, job)
        message = f"{headline} — last run said: {reason}" if reason else headline

        logger.warning("watchdog: %s", message)
        if _persist_notification(session, source=job, message=message, today=today, kind="output"):
            _pushover_send(message)
            report[job]["alerted"] = True

    return report
