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

import httpx
from celery.schedules import crontab
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.celery_app import app
from app.cii.scoring import CII_METHOD_VERSION
from app.cii.task import _compute_cii_body
from app.composite.task import _compute_composite_body
from app.db import session_scope
from app.db_models import EventRow, IngestFailureRow, IngestHealthRow
from app.enrichment.footprint import USER_AGENT, footprint_for_event
from app.fetcher_registry import get_fetcher
from app.housekeeping import prune_events
from app.persistence import upsert_events
from app.sources.rss_registry import feed_cadence_map
from app.watchdog import check_sources

#: Hazard sources whose real footprint geometry we enrich (issue #205).
_FOOTPRINT_SOURCES: tuple[str, ...] = ("usgs-quake", "gdacs", "eonet")


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


@app.task(
    name="app.tasks.compute_cii",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def compute_cii(method_version: str = CII_METHOD_VERSION) -> dict[str, Any]:
    """Run the CII worker (read 24 h of events, score per country, upsert).

    Methodology: docs/architecture/CII-METHODOLOGY.md. Always runs alongside
    the composite worker; the two coexist on the ``scores`` table via the
    ``score_name`` discriminator.
    """
    return _compute_cii_body(method_version=method_version)


def _enrich_footprints_body(
    *, limit: int = 200, client: httpx.Client | None = None
) -> dict[str, Any]:
    """Backfill real footprint geometry onto hazard events missing it.

    Walks the most recent hazard rows (USGS quakes / GDACS events) that have no
    ``payload.footprint_geojson`` yet, fetches the real geometry from upstream,
    and writes it into the payload. Best-effort: any single fetch failing leaves
    that row untouched for the next run. ``upsert_events`` never updates existing
    rows (ON CONFLICT DO NOTHING), so this is the only path that mutates them.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT})
    scanned = 0
    enriched = 0
    try:
        with session_scope() as session:
            stmt = (
                select(EventRow)
                .where(EventRow.source.in_(_FOOTPRINT_SOURCES))
                .order_by(EventRow.occurred_at.desc())
                .limit(limit)
            )
            for row in session.execute(stmt).scalars():
                payload = dict(row.payload or {})
                if "footprint_geojson" in payload:
                    continue
                scanned += 1
                geojson = footprint_for_event(row.source, payload, client=client)
                if geojson is None:
                    continue
                payload["footprint_geojson"] = geojson
                row.payload = payload  # reassign so SQLAlchemy flags the jsonb dirty
                enriched += 1
    finally:
        if owns_client:
            client.close()
    return {"scanned": scanned, "enriched": enriched}


@app.task(
    name="app.tasks.enrich_footprints",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def enrich_footprints(limit: int = 200) -> dict[str, Any]:
    """Celery entry point for real hazard footprint enrichment (issue #205)."""
    return _enrich_footprints_body(limit=limit)


@app.task(name="app.tasks.ingest_watchdog")
def ingest_watchdog() -> dict[str, Any]:
    """Walk ingest_health and flag any source whose last_success has gone stale."""
    with session_scope() as session:
        return check_sources(session)


@app.task(name="app.tasks.run_housekeeping")
def run_housekeeping() -> dict[str, int]:
    """Apply per-source retention to the events table.

    NASA FIRMS ingests ~35 k rows/day; without this the table fills the
    local disk within weeks without pruning. See ``app.housekeeping`` for the
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
    "acled-hourly": {
        "task": "app.tasks.run_fetcher",
        "args": ["acled"],
        "schedule": crontab(hour="*/1", minute=5),
    },
    "emdat-daily-7-30am-utc": {
        "task": "app.tasks.run_fetcher",
        "args": ["emdat"],
        "schedule": crontab(hour=7, minute=30),
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
    # RSS news feeds — generated from app/sources/rss_feeds.json. Each
    # entry is hourly by default, staggered by the feed's index so they
    # never all hit upstream at the same instant. See issue #158.
    **{
        f"{slug}-hourly": {
            "task": "app.tasks.run_fetcher",
            "args": [slug],
            "schedule": crontab(hour="*/1", minute=(10 + idx * 2) % 60),
        }
        for idx, slug in enumerate(feed_cadence_map().keys())
    },
    # UK Police publishes one month of crime data at a time; a daily 6 AM
    # poll is plenty. Cheap fetcher in absolute terms (6 cities x ~4 k rows
    # /month). Avoids hammering the public API.
    "uk-police-daily-6am-utc": {
        "task": "app.tasks.run_fetcher",
        "args": ["uk-police"],
        "schedule": crontab(hour=6, minute=0),
    },
    # OpenSky public ADS-B is rate-limited per anonymous IP at 10 s; we
    # poll every 2 min to stay polite to the upstream source.
    "opensky-adsb-2min": {
        "task": "app.tasks.run_fetcher",
        "args": ["opensky-adsb"],
        "schedule": crontab(minute="*/2"),
    },
    # abuse.ch cyber-threat feeds. Refresh upstream every ~5 min; we
    # poll every 15 min to be polite. Two slots offset by 3 min so
    # they don't fire simultaneously.
    "abuse-ch-urlhaus-15min": {
        "task": "app.tasks.run_fetcher",
        "args": ["abuse-ch-urlhaus"],
        "schedule": crontab(minute="3,18,33,48"),
    },
    "abuse-ch-feodo-15min": {
        "task": "app.tasks.run_fetcher",
        "args": ["abuse-ch-feodo"],
        "schedule": crontab(minute="6,21,36,51"),
    },
    # Polymarket public Gamma API — prediction markets refresh every
    # few seconds. 30 min cadence keeps the dashboard fresh without
    # blowing the write quota or hammering the public endpoint.
    "polymarket-30min": {
        "task": "app.tasks.run_fetcher",
        "args": ["polymarket"],
        "schedule": crontab(minute="9,39"),
    },
    "composite-hourly": {
        "task": "app.tasks.compute_composite",
        "schedule": crontab(hour="*/1", minute=10),
    },
    "cii-hourly": {
        "task": "app.tasks.compute_cii",
        "schedule": crontab(hour="*/1", minute=25),
    },
    # Real hazard footprint geometry (issue #205). Runs a few minutes after the
    # USGS/GDACS fetchers so freshly-ingested events get their real shapes.
    "enrich-footprints-15min": {
        "task": "app.tasks.enrich_footprints",
        "schedule": crontab(minute="11,26,41,56"),
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
