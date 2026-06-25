"""Local read-API for the dashboard frontend. Replaces Supabase REST.

Read-only over the local Postgres. Serves recent events + latest scores, and
(see SSE task) a live stream. Run with: uvicorn app.api:app --port 8000
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.db_models import EventRow, ScoreRow
from app.events_bus import subscribe_new_events
from app.settings import settings

app = FastAPI(title="OSINT local API", version="1.0")
app.state.event_source = subscribe_new_events

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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/events")
def events(
    session: Session = Depends(get_session),
    since: datetime | None = Query(default=None),
    sources: str | None = Query(default=None),
    exclude: str | None = Query(default=None),
    limit: int = Query(default=5000, le=10000),
) -> list[dict]:
    stmt = select(EventRow).order_by(EventRow.occurred_at.desc()).limit(limit)
    if since is not None:
        stmt = stmt.where(EventRow.occurred_at >= since)
    if sources:
        stmt = stmt.where(EventRow.source.in_([s.strip() for s in sources.split(",")]))
    if exclude:
        stmt = stmt.where(EventRow.source.notin_([s.strip() for s in exclude.split(",")]))
    return [_event_dict(r) for r in session.execute(stmt).scalars()]


@app.get("/scores")
def scores(
    session: Session = Depends(get_session),
    limit: int = Query(default=5000, le=10000),
) -> list[dict]:
    stmt = select(ScoreRow).order_by(ScoreRow.bucket_start.desc()).limit(limit)
    return [_score_dict(r) for r in session.execute(stmt).scalars()]


@app.get("/stream")
def stream() -> StreamingResponse:
    source = app.state.event_source

    def gen():
        yield ": connected\n\n"  # prelude so EventSource fires onopen
        for count in source():
            yield f"data: {count}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
