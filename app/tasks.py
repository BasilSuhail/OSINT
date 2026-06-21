"""Celery tasks.

`run_fetcher(name)` is the universal task wrapper: it resolves a fetcher by
name, runs its `fetch()` method, persists the events idempotently, and
records the outcome in `ingest_health` (success) or `ingest_failures` (failure).

The task body lives in `_run_fetcher_body()` so it can be unit tested without
going through Celery's broker.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from celery.schedules import crontab
from sqlalchemy.orm import Session

from app.celery_app import app
from app.composite.task import _compute_composite_body
from app.db import session_scope
from app.db_models import IngestFailureRow, IngestHealthRow
from app.fetcher_registry import get_fetcher
from app.housekeeping import prune_events
from app.persistence import upsert_events
from app.watchdog import check_sources


def _record_success(session: Session, *, source: str) -> None:
    today = date.today()
    now = datetime.now(UTC)
    row = session.get(IngestHealthRow, (source, today))
    if row is None:
        session.add(IngestHealthRow(source=source, day=today, success_n=1, last_success=now))
    else:
        row.success_n = (row.success_n or 0) + 1
        row.last_success = now


def _record_failure(session: Session, *, source: str, exc: BaseException) -> None:
    today = date.today()
    now = datetime.now(UTC)
    row = session.get(IngestHealthRow, (source, today))
    if row is None:
        session.add(IngestHealthRow(source=source, day=today, failure_n=1, last_failure=now))
    else:
        row.failure_n = (row.failure_n or 0) + 1
        row.last_failure = now
    session.add(
        IngestFailureRow(
            source=source,
            error_class=type(exc).__name__,
            error_message=str(exc),
        )
    )


def _run_fetcher_body(name: str) -> dict[str, Any]:
    """Plain-function task body — testable without Celery."""
    fetcher = get_fetcher(name)
    try:
        events = fetcher.fetch()
    except Exception as exc:
        with session_scope() as session:
            _record_failure(session, source=name, exc=exc)
        raise

    with session_scope() as session:
        inserted = upsert_events(events, session)
        _record_success(session, source=name)
    return {"fetched": len(events), "inserted": inserted}


@app.task(
    name="app.tasks.run_fetcher",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
)
def run_fetcher(name: str) -> dict[str, Any]:
    """Celery entry point. Delegates to `_run_fetcher_body()`."""
    return _run_fetcher_body(name)


@app.task(
    name="app.tasks.compute_composite",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def compute_composite(method_version: str = "v1.0") -> dict[str, Any]:
    """Run the composite worker (read events, aggregate, normalise, score, upsert)."""
    return _compute_composite_body(method_version=method_version)


@app.task(name="app.tasks.ingest_watchdog")
def ingest_watchdog() -> dict[str, Any]:
    """Walk ingest_health and flag any source whose last_success has gone stale."""
    with session_scope() as session:
        return check_sources(session)


@app.task(name="app.tasks.run_housekeeping")
def run_housekeeping() -> dict[str, int]:
    """Apply per-source retention to the events table.

    NASA FIRMS ingests ~35 k rows/day; without this the table fills the
    Supabase free tier in roughly two weeks. See ``app.housekeeping`` for the
    per-source policy.
    """
    with session_scope() as session:
        return prune_events(session)


# Beat schedule — declarative cadence per source. Matches the table in
# docs/architecture/03-ingestion.md.
app.conf.beat_schedule = {
    "yfinance-5min": {
        "task": "app.tasks.run_fetcher",
        "args": ["yfinance"],
        "schedule": crontab(minute="*/5"),
    },
    "fred-daily-7am-utc": {
        "task": "app.tasks.run_fetcher",
        "args": ["fred"],
        "schedule": crontab(hour=7, minute=0),
    },
    "gdelt-15min": {
        "task": "app.tasks.run_fetcher",
        "args": ["gdelt"],
        "schedule": crontab(minute="0,15,30,45"),
    },
    "usgs-quake-15min": {
        "task": "app.tasks.run_fetcher",
        "args": ["usgs-quake"],
        "schedule": crontab(minute="2,17,32,47"),
    },
    "gdacs-15min": {
        "task": "app.tasks.run_fetcher",
        "args": ["gdacs"],
        "schedule": crontab(minute="4,19,34,49"),
    },
    "nasa-firms-hourly": {
        "task": "app.tasks.run_fetcher",
        "args": ["nasa-firms"],
        "schedule": crontab(hour="*/1", minute=6),
    },
    "eonet-30min": {
        "task": "app.tasks.run_fetcher",
        "args": ["eonet"],
        "schedule": crontab(minute="8,38"),
    },
    # RSS news feeds: hourly, staggered by 2 minutes so all six aren't
    # hitting their upstream at the same instant.
    "rss-bbc-world-hourly": {
        "task": "app.tasks.run_fetcher",
        "args": ["rss-bbc-world"],
        "schedule": crontab(hour="*/1", minute=11),
    },
    "rss-bbc-uk-hourly": {
        "task": "app.tasks.run_fetcher",
        "args": ["rss-bbc-uk"],
        "schedule": crontab(hour="*/1", minute=13),
    },
    "rss-reuters-world-hourly": {
        "task": "app.tasks.run_fetcher",
        "args": ["rss-reuters-world"],
        "schedule": crontab(hour="*/1", minute=15),
    },
    "rss-dawn-hourly": {
        "task": "app.tasks.run_fetcher",
        "args": ["rss-dawn"],
        "schedule": crontab(hour="*/1", minute=17),
    },
    "rss-guardian-world-hourly": {
        "task": "app.tasks.run_fetcher",
        "args": ["rss-guardian-world"],
        "schedule": crontab(hour="*/1", minute=19),
    },
    "rss-geo-english-hourly": {
        "task": "app.tasks.run_fetcher",
        "args": ["rss-geo-english"],
        "schedule": crontab(hour="*/1", minute=21),
    },
    # UK Police publishes one month of crime data at a time; a daily 6 AM
    # poll is plenty. Cheap fetcher in absolute terms (6 cities x ~4 k rows
    # /month). Avoids hammering the public API.
    "uk-police-daily-6am-utc": {
        "task": "app.tasks.run_fetcher",
        "args": ["uk-police"],
        "schedule": crontab(hour=6, minute=0),
    },
    "composite-hourly": {
        "task": "app.tasks.compute_composite",
        "schedule": crontab(hour="*/1", minute=10),
    },
    "ingest-watchdog-15min": {
        "task": "app.tasks.ingest_watchdog",
        "schedule": crontab(minute="*/15"),
    },
    "housekeeping-daily-3am-utc": {
        "task": "app.tasks.run_housekeeping",
        "schedule": crontab(hour=3, minute=0),
    },
}
