"""Local read-API for the dashboard frontend. Replaces Supabase REST.

Read-only over the local Postgres. Serves recent events + latest scores, and
(see SSE task) a live stream. Run with: uvicorn app.api:app --port 8000
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.db_models import EventRow, IngestHealthRow, ScoreRow
from app.events_bus import subscribe_new_events
from app.settings import settings

app = FastAPI(title="OSINT local API", version="1.0")
app.state.event_source = subscribe_new_events
API_MAX_LIMIT = 20_000

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.api_cors_origins.split(",") if o.strip()],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def _event_dict(row: EventRow) -> dict:
    return {
        "id": str(row.id),
        "source": row.source,
        "source_event_id": row.source_event_id,
        "occurred_at": row.occurred_at.isoformat(),
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        "category": row.category,
        "severity": row.severity,
        "confidence": row.confidence,
        "keywords": list(row.keywords or []),
        "country": row.country,
        "lat": row.lat,
        "lon": row.lon,
        "payload": row.payload,
    }


def _score_dict(row: ScoreRow) -> dict:
    return {
        "country": row.country,
        "bucket_start": row.bucket_start.isoformat(),
        "score_name": row.score_name,
        "score_value": row.score_value,
        "components": row.components,
        "method_version": row.method_version,
    }


def _ingest_health_dict(row: IngestHealthRow) -> dict:
    return {
        "source": row.source,
        "day": row.day.isoformat(),
        "success_n": row.success_n,
        "failure_n": row.failure_n,
        "last_success": row.last_success.isoformat() if row.last_success else None,
        "last_failure": row.last_failure.isoformat() if row.last_failure else None,
    }


def _source_coverage_dict(row) -> dict:
    return {
        "source": row.source,
        "total": row.total,
        "recent": row.recent,
        "geocoded": row.geocoded,
        "latest_occurred_at": (
            row.latest_occurred_at.isoformat() if row.latest_occurred_at else None
        ),
        "latest_fetched_at": row.latest_fetched_at.isoformat() if row.latest_fetched_at else None,
    }


@app.get("/ingest-health")
def ingest_health(
    session: Session = Depends(get_session),
    days: int = Query(default=7, ge=0),
    limit: int = Query(default=2000, ge=1, le=5000),
) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    stmt = (
        select(IngestHealthRow)
        .where(IngestHealthRow.day >= cutoff)
        .order_by(IngestHealthRow.day.desc())
        .limit(limit)
    )
    return [_ingest_health_dict(r) for r in session.execute(stmt).scalars()]


@app.get("/events/coverage")
def event_coverage(
    session: Session = Depends(get_session),
    days: int = Query(default=30, ge=0, le=365),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict]:
    """Per-source counts used to audit DB/API/frontend visibility.

    This endpoint is intentionally aggregate-only: it lets the dashboard prove
    that sparse feeds exist in the database even when `/events` is capped or
    map rendering intentionally drops ungeocoded rows.
    """

    cutoff = datetime.now(UTC) - timedelta(days=days)
    recent_count = func.sum(case((EventRow.occurred_at >= cutoff, 1), else_=0))
    geocoded_count = func.sum(
        case((EventRow.lat.is_not(None) & EventRow.lon.is_not(None), 1), else_=0)
    )
    stmt = (
        select(
            EventRow.source.label("source"),
            func.count(EventRow.id).label("total"),
            recent_count.label("recent"),
            geocoded_count.label("geocoded"),
            func.max(EventRow.occurred_at).label("latest_occurred_at"),
            func.max(EventRow.fetched_at).label("latest_fetched_at"),
        )
        .group_by(EventRow.source)
        .order_by(func.max(EventRow.fetched_at).desc())
        .limit(limit)
    )
    return [_source_coverage_dict(r) for r in session.execute(stmt)]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/events")
def events(
    session: Session = Depends(get_session),
    since: datetime | None = Query(default=None),
    fetched_since: datetime | None = Query(default=None),
    sources: str | None = Query(default=None),
    exclude: str | None = Query(default=None),
    country: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=API_MAX_LIMIT),
) -> list[dict]:
    stmt = select(EventRow).order_by(EventRow.occurred_at.desc()).limit(limit)
    if since is not None:
        stmt = stmt.where(EventRow.occurred_at >= since)
    if fetched_since is not None:
        stmt = stmt.where(EventRow.fetched_at >= fetched_since)
    if sources:
        stmt = stmt.where(EventRow.source.in_([s.strip() for s in sources.split(",")]))
    if exclude:
        stmt = stmt.where(EventRow.source.notin_([s.strip() for s in exclude.split(",")]))
    if country is not None:
        stmt = stmt.where(EventRow.country == country)
    return [_event_dict(r) for r in session.execute(stmt).scalars()]


@app.get("/scores")
def scores(
    session: Session = Depends(get_session),
    score_name: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    country: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=API_MAX_LIMIT),
) -> list[dict]:
    stmt = select(ScoreRow).order_by(ScoreRow.bucket_start.desc()).limit(limit)
    if score_name is not None:
        stmt = stmt.where(ScoreRow.score_name == score_name)
    if since is not None:
        stmt = stmt.where(ScoreRow.bucket_start >= since)
    if country is not None:
        stmt = stmt.where(ScoreRow.country == country)
    return [_score_dict(r) for r in session.execute(stmt).scalars()]


@app.get("/stream")
def stream() -> StreamingResponse:
    source = app.state.event_source

    def gen():
        yield ": connected\n\n"  # prelude so EventSource fires onopen
        for count in source():
            if count is None:
                yield ": keepalive\n\n"
                continue
            yield f"data: {count}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
