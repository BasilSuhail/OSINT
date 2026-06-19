"""Celery tasks.

`run_fetcher(name)` is the universal task wrapper: it resolves a fetcher by
name, runs its `fetch()` method, persists the events idempotently, and
records the outcome in `ingest_health` (success) or `ingest_failures` (failure).

The task body lives in `_run_fetcher_body()` so it can be unit tested without
going through Celery's broker.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from celery.schedules import crontab
from sqlalchemy.orm import Session

from app.celery_app import app
from app.db import session_scope
from app.db_models import IngestFailureRow, IngestHealthRow
from app.fetcher_registry import get_fetcher
from app.persistence import upsert_events


def _record_success(session: Session, *, source: str) -> None:
    today = date.today()
    now = datetime.now(timezone.utc)
    row = session.get(IngestHealthRow, (source, today))
    if row is None:
        session.add(
            IngestHealthRow(source=source, day=today, success_n=1, last_success=now)
        )
    else:
        row.success_n = (row.success_n or 0) + 1
        row.last_success = now


def _record_failure(session: Session, *, source: str, exc: BaseException) -> None:
    today = date.today()
    now = datetime.now(timezone.utc)
    row = session.get(IngestHealthRow, (source, today))
    if row is None:
        session.add(
            IngestHealthRow(source=source, day=today, failure_n=1, last_failure=now)
        )
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
    except Exception as exc:  # noqa: BLE001 - we want to log every fetch failure
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
}
