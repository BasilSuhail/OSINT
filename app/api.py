"""Local read-API for the dashboard frontend. Replaces Supabase REST.

Read-only over the local Postgres. Serves recent events + latest scores, and
(see SSE task) a live stream. Run with: uvicorn app.api:app --port 8000
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.db_models import (
    EventRow,
    IngestHealthRow,
    JobRunRow,
    PredictionRow,
    ScoreRow,
    StoryCorroborationRow,
    StoryRow,
    StorySensorCheckRow,
)
from app.events_bus import subscribe_new_events
from app.journal.scoreboard import build_scoreboard
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


@app.get("/stories/top")
def stories_top(
    session: Session = Depends(get_session),
    hours: int = Query(default=24, ge=1, le=24 * 90),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict]:
    """Story clusters seen in the last `hours`, loudest (most outlets) first.

    Each story carries its corroboration-v1.0 score with the full evidence
    trail (WS-C step 5, #365) — null until the corroboration beat has scored
    it — plus the claim → verdict map from the sensor cross-checks.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    stmt = (
        select(StoryRow, StoryCorroborationRow)
        .outerjoin(StoryCorroborationRow, StoryCorroborationRow.story_id == StoryRow.id)
        .where(StoryRow.last_seen >= cutoff)
        .order_by(StoryRow.outlet_count.desc(), StoryRow.member_count.desc())
        .limit(limit)
    )
    rows = session.execute(stmt).all()

    checks: dict[int, dict[str, str]] = {}
    story_ids = [story.id for story, _ in rows]
    if story_ids:
        for check in session.execute(
            select(StorySensorCheckRow).where(StorySensorCheckRow.story_id.in_(story_ids))
        ).scalars():
            checks.setdefault(check.story_id, {})[check.claim_type] = check.verdict

    return [
        {
            "id": str(story.id),
            "title": story.title,
            "first_seen": story.first_seen.isoformat(),
            "last_seen": story.last_seen.isoformat(),
            "member_count": story.member_count,
            "outlet_count": story.outlet_count,
            "owner_count": story.owner_count,
            "corroboration": corro.score if corro else None,
            "corroboration_components": corro.components if corro else None,
            "sensor_checks": checks.get(story.id, {}),
            "method_version": story.method_version,
        }
        for story, corro in rows
    ]


@app.get("/stories/{story_id}/members")
def story_members(
    story_id: int,
    session: Session = Depends(get_session),
) -> list[dict]:
    """Drilldown (#396): who told this story, and how alike the tellings are.

    One row per member article — outlet, independent owner, origin country,
    join similarity. Fetched lazily when a story row is expanded.
    """
    from app.db_models import StoryMemberRow
    from app.sources.rss_registry import content_owner_map, load_feed_configs, outlet_country_map

    owners = content_owner_map()
    origins = outlet_country_map()
    pretty = {cfg.source: cfg.pretty_name for cfg in load_feed_configs()}

    rows = session.execute(
        select(StoryMemberRow, EventRow)
        .join(EventRow, EventRow.id == StoryMemberRow.event_id)
        .where(StoryMemberRow.story_id == story_id)
        .order_by(EventRow.occurred_at)
    ).all()
    return [
        {
            "title": (event.payload or {}).get("title") or "",
            "source": event.source,
            "outlet": pretty.get(event.source, event.source),
            "owner": owners.get(event.source, event.source),
            "origin_country": origins.get(event.source),
            "occurred_at": event.occurred_at.isoformat(),
            "similarity": member.similarity,
        }
        for member, event in rows
    ]


@app.get("/journal/monthly")
def journal_monthly(session: Session = Depends(get_session)) -> list[dict]:
    """Drilldown (#396): the track record over time, per instrument per month.

    Month = issuance month (bucket_start). Brier is computed over graded rows
    only; months with no grades yet report brier null — honest pending state.
    """
    rows = session.execute(select(PredictionRow)).scalars().all()
    grouped: dict[tuple[str, str], dict] = {}
    for row in rows:
        month = row.bucket_start.strftime("%Y-%m-01")
        slot = grouped.setdefault(
            (row.source, month),
            {"source": row.source, "month": month, "issued": 0, "graded": 0, "_sq": 0.0},
        )
        slot["issued"] += 1
        if row.outcome is not None:
            slot["graded"] += 1
            slot["_sq"] += (row.score - row.outcome) ** 2
    out = []
    for slot in grouped.values():
        sq = slot.pop("_sq")
        slot["brier"] = sq / slot["graded"] if slot["graded"] else None
        out.append(slot)
    out.sort(key=lambda s: (s["source"], s["month"]))
    return out


@app.get("/jobs/recent")
def jobs_recent(
    session: Session = Depends(get_session),
    hours: int = Query(default=48, ge=1, le=24 * 14),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    """Recent job runs, newest first — the top-bar activity monitor's feed.

    Stalled detection is the reader's job: status == "running" with a
    heartbeat older than ~10 minutes means the process died mid-run.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    stmt = (
        select(JobRunRow)
        .where(JobRunRow.started_at >= cutoff)
        .order_by(JobRunRow.started_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": row.id,
            "job": row.job,
            "status": row.status,
            "started_at": row.started_at.isoformat(),
            "heartbeat_at": row.heartbeat_at.isoformat(),
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "progress": row.progress,
            "detail": row.detail,
        }
        for row in session.execute(stmt).scalars()
    ]


@app.get("/journal/scoreboard")
def journal_scoreboard(session: Session = Depends(get_session)) -> list[dict]:
    """Forward-prediction track record per source x horizon."""
    rows = [
        {
            "source": row.source,
            "method_version": row.method_version,
            "horizon_months": row.horizon_months,
            "score": row.score,
            "outcome": row.outcome,
        }
        for row in session.execute(select(PredictionRow)).scalars()
    ]
    return build_scoreboard(rows)


def _export_report(filename: str, hint: str) -> dict:
    path = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found — run `{hint}` first")
    return json.loads(path.read_text())


@app.get("/analytics/baselines")
def analytics_baselines() -> dict:
    """Latest baselines report exactly as `make baselines` wrote it."""
    return _export_report("baselines-report.json", "make baselines")


@app.get("/analytics/coverage")
def analytics_coverage() -> dict:
    """Latest coverage-bias report exactly as `make coverage` wrote it."""
    return _export_report("coverage-bias.json", "make coverage")


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
