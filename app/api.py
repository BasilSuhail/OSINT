"""Local read-API for the dashboard frontend. Replaces Supabase REST.

Read-only over the local Postgres. Serves recent events + latest scores, and
(see SSE task) a live stream. Run with: uvicorn app.api:app --port 8000
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.article_collapse import collapse_article_relations
from app.brain import client, context, deepread, enrich, gate, qa
from app.composite import degeneracy as composite_degeneracy
from app.db import get_session_factory
from app.db_models import (
    AuditFindingRow,
    AuditRunRow,
    BrainNarrativeRow,
    EventRow,
    IngestHealthRow,
    JobRunRow,
    PredictionRow,
    ScoreRow,
    SourceQuarantineRow,
    StoryCorroborationRow,
    StoryGistRow,
    StoryRow,
    StorySensorCheckRow,
)
from app.events_bus import subscribe_new_events
from app.journal.scoreboard import build_scoreboard
from app.paths import exports_dir
from app.settings import settings
from app.stories import developing

app = FastAPI(title="OSINT local API", version="1.0")
app.state.event_source = subscribe_new_events
API_MAX_LIMIT = settings.api_max_limit
API_DEFAULT_LIMIT = min(settings.api_default_limit, API_MAX_LIMIT)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.api_cors_origins.split(",") if o.strip()],
    # POST is required for the browser's preflight on /brain/ask (#419); GET-only
    # made every ask-the-brain request fail CORS as "offline".
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def get_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def _event_dict(row: EventRow) -> dict:
    updated_at = row.updated_at
    if updated_at is not None and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return {
        "id": str(row.id),
        "source": row.source,
        "source_event_id": row.source_event_id,
        "occurred_at": row.occurred_at.isoformat(),
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        # Canonical UTC preserves PostgreSQL microseconds for the composite
        # revision cursor; JavaScript Date would truncate this boundary.
        "updated_at": updated_at.astimezone(UTC).isoformat() if updated_at else None,
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


@app.get("/ingest/quarantine")
def ingest_quarantine(session: Session = Depends(get_session)) -> list[dict]:
    """Sources being rested because they cannot currently succeed (#567).

    An empty list is the healthy state. Each entry says what broke, how long it
    has been broken, and when it will be tried again — a dead feed should be
    visible, not merely absent from the success counts.
    """
    rows = session.execute(
        select(SourceQuarantineRow).order_by(SourceQuarantineRow.retry_after)
    ).scalars()
    return [
        {
            "source": row.source,
            "kind": row.kind,
            "http_status": row.http_status,
            "detail": row.detail,
            "consecutive_failures": row.consecutive_failures,
            "first_failed_at": row.first_failed_at.isoformat(),
            "last_failed_at": row.last_failed_at.isoformat(),
            "retry_after": row.retry_after.isoformat(),
        }
        for row in rows
    ]


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


def _epoch_seconds(session: Session, column):
    """Seconds-since-epoch for a timestamp column, per dialect.

    Postgres and SQLite spell this differently and neither expression parses on
    the other, so the branch belongs here rather than in the caller.
    """
    if session.bind is not None and session.bind.dialect.name == "sqlite":
        return func.strftime("%s", column) * 1.0
    return func.extract("epoch", column)


#: Sources the dashboard cannot render, excluded from headline stats by default.
#: FIRMS lost its only renderer with the globe (#494); opensky is a per-country
#: hourly aggregate since #496 and was never drawn. Counting either would inflate
#: the header with events the user can neither see nor click.
NON_RENDERABLE_SOURCES: tuple[str, ...] = ("nasa-firms", "opensky-adsb")

#: Sparkline resolution. Matches WORLD_STATS_SPARK_BUCKETS on the frontend.
STATS_SPARK_BUCKETS = 24

#: How many countries the ranked list returns. Matches WORLD_STATS_TOP_N.
STATS_TOP_N = 12


@app.get("/events/stats")
def event_stats(
    session: Session = Depends(get_session),
    days: int = Query(default=30, ge=0, le=365),
    exclude: str | None = Query(default=None),
) -> dict:
    """Headline counts for the world-status panel, aggregated in Postgres.

    The panel used to derive these from the client's event buffer, so the
    numbers described the buffer cap (7,500) rather than the data. Counting
    here keeps the figures true at constant browser memory.

    `exclude` replaces the `NON_RENDERABLE_SOURCES` default when supplied.
    """

    cutoff = datetime.now(UTC) - timedelta(days=days)
    skipped = (
        [s.strip() for s in exclude.split(",") if s.strip()]
        if exclude is not None
        else list(NON_RENDERABLE_SOURCES)
    )

    def _windowed(stmt):
        stmt = stmt.where(EventRow.occurred_at >= cutoff)
        if skipped:
            stmt = stmt.where(EventRow.source.notin_(skipped))
        return stmt

    totals = session.execute(
        _windowed(
            select(
                func.count(EventRow.id),
                func.count(func.distinct(EventRow.country)),
                func.count(func.distinct(EventRow.source)),
            )
        )
    ).one()

    top = session.execute(
        _windowed(
            select(EventRow.country, func.count(EventRow.id).label("count"))
            .where(EventRow.country.is_not(None))
            .group_by(EventRow.country)
        )
        .order_by(func.count(EventRow.id).desc(), EventRow.country)
        .limit(STATS_TOP_N)
    ).all()

    # Bucket oldest→newest across the requested window, counted in the database.
    # Pulling the timestamps into Python would ship one row per event on every
    # poll — the exact cost this endpoint exists to remove.
    spark = [0] * STATS_SPARK_BUCKETS
    span = (datetime.now(UTC) - cutoff).total_seconds()
    if span > 0:
        epoch = _epoch_seconds(session, EventRow.occurred_at)
        bucket = func.cast(
            func.floor((epoch - cutoff.timestamp()) / (span / STATS_SPARK_BUCKETS)),
            sa.Integer,
        )
        rows = session.execute(
            _windowed(select(bucket.label("bucket"), func.count(EventRow.id))).group_by("bucket")
        ).all()
        for idx, count in rows:
            spark[min(max(int(idx), 0), STATS_SPARK_BUCKETS - 1)] += count

    return {
        "total": totals[0],
        "countries": totals[1],
        "sources": totals[2],
        "top_countries": [{"country": c, "count": n} for c, n in top],
        "spark": spark,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/events")
def events(
    session: Session = Depends(get_session),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    fetched_since: datetime | None = Query(default=None),
    updated_since: datetime | None = Query(default=None),
    updated_after_id: int | None = Query(default=None, ge=0),
    occurred_before: datetime | None = Query(default=None),
    occurred_before_id: int | None = Query(default=None, ge=0),
    west: float | None = Query(default=None, ge=-180, le=180),
    south: float | None = Query(default=None, ge=-90, le=90),
    east: float | None = Query(default=None, ge=-180, le=180),
    north: float | None = Query(default=None, ge=-90, le=90),
    positioned_only: bool = Query(default=False),
    sources: str | None = Query(default=None),
    exclude: str | None = Query(default=None),
    country: str | None = Query(default=None),
    collapse: bool = Query(default=True),
    limit: int = Query(default=API_DEFAULT_LIMIT, ge=1, le=API_MAX_LIMIT),
) -> list[dict]:
    bbox = (west, south, east, north)
    if any(value is not None for value in bbox) and not all(value is not None for value in bbox):
        raise HTTPException(
            status_code=422,
            detail="west, south, east, and north are required together",
        )
    if south is not None and north is not None and south > north:
        raise HTTPException(status_code=422, detail="south must not exceed north")
    if occurred_before_id is not None and occurred_before is None:
        raise HTTPException(status_code=422, detail="occurred_before_id requires occurred_before")
    if occurred_before is not None and updated_since is not None:
        raise HTTPException(
            status_code=422,
            detail="occurrence and revision cursors cannot be combined",
        )

    stmt = select(EventRow)
    if since is not None:
        stmt = stmt.where(EventRow.occurred_at >= since)
    if until is not None:
        stmt = stmt.where(EventRow.occurred_at <= until)
    if fetched_since is not None:
        stmt = stmt.where(EventRow.fetched_at >= fetched_since)
    if updated_since is not None:
        if updated_after_id is None:
            stmt = stmt.where(EventRow.updated_at > updated_since)
        else:
            # PostgreSQL now() is transaction-scoped, so thousands of rows can
            # share one revision. Pair the timestamp with the primary key or a
            # limited page would permanently skip the rest of that boundary.
            stmt = stmt.where(
                sa.or_(
                    EventRow.updated_at > updated_since,
                    sa.and_(
                        EventRow.updated_at == updated_since,
                        EventRow.id > updated_after_id,
                    ),
                )
            )
    if sources:
        stmt = stmt.where(EventRow.source.in_([s.strip() for s in sources.split(",")]))
    if exclude:
        stmt = stmt.where(EventRow.source.notin_([s.strip() for s in exclude.split(",")]))
    if country is not None:
        stmt = stmt.where(EventRow.country == country)
    if west is not None and south is not None and east is not None and north is not None:

        def longitude_in_bounds(column):
            return (
                column.between(west, east)
                if west <= east
                else sa.or_(column >= west, column <= east)
            )

        # Multi-place stories keep one primary coordinate on the row and every
        # independently verified point in payload.place_locations (#748). A
        # viewport containing a secondary place must recover the story too.
        primary_position = sa.and_(
            EventRow.lat.between(south, north),
            longitude_in_bounds(EventRow.lon),
        )
        if session.bind is not None and session.bind.dialect.name == "sqlite":
            places = func.json_each(EventRow.payload, "$.place_locations").table_valued("value")
            place_lat = sa.cast(func.json_extract(places.c.value, "$.lat"), sa.Float)
            place_lon = sa.cast(func.json_extract(places.c.value, "$.lon"), sa.Float)
        else:
            raw_places = EventRow.payload["place_locations"]
            place_array = sa.case(
                (func.jsonb_typeof(raw_places) == "array", raw_places),
                else_=sa.literal_column("'[]'::jsonb"),
            )
            places = func.jsonb_array_elements(place_array).table_valued("value")
            place_lat = sa.cast(func.jsonb_extract_path_text(places.c.value, "lat"), sa.Float)
            place_lon = sa.cast(func.jsonb_extract_path_text(places.c.value, "lon"), sa.Float)
        payload_position = sa.exists(
            select(1)
            .select_from(places)
            .where(
                place_lat.between(south, north),
                longitude_in_bounds(place_lon),
            )
        )
        stmt = stmt.where(sa.or_(primary_position, payload_position))
    elif positioned_only:
        stmt = stmt.where(EventRow.lat.is_not(None), EventRow.lon.is_not(None))
    if occurred_before is not None:
        if occurred_before_id is None:
            stmt = stmt.where(EventRow.occurred_at < occurred_before)
        else:
            stmt = stmt.where(
                sa.or_(
                    EventRow.occurred_at < occurred_before,
                    sa.and_(
                        EventRow.occurred_at == occurred_before,
                        EventRow.id < occurred_before_id,
                    ),
                )
            )
    # One GDELT article arrives as one row per actor pairing, so a list shows
    # the same headline three times (#772). Collapse before the limit: a page
    # thinned afterwards is a short page, and `fetchAllEventPages` reads a
    # short page as the end of the data.
    row_source: Any = EventRow
    if collapse:
        row_source, relation_count, survivor = collapse_article_relations(stmt)
        stmt = select(row_source).add_columns(relation_count).where(survivor)

    # Incremental consumers advance a high-water mark. Oldest-first prevents a
    # burst larger than `limit` from skipping the middle when that mark moves.
    if updated_since is not None:
        stmt = stmt.order_by(row_source.updated_at.asc(), row_source.id.asc())
    else:
        stmt = stmt.order_by(row_source.occurred_at.desc(), row_source.id.desc())
    stmt = stmt.limit(limit)
    if not collapse:
        return [_event_dict(r) | {"relation_count": 1} for r in session.execute(stmt).scalars()]
    return [
        _event_dict(row) | {"relation_count": int(relations)}
        for row, relations in session.execute(stmt).all()
    ]


@app.get("/search")
def search_everything(
    session: Session = Depends(get_session),
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=40, ge=1, le=200),
) -> dict:
    """One query, answered as places, content, or both (#779).

    Places come from the bundled gazetteer — no third-party geocoder, so
    typing costs nothing and never fails. Content comes from a full-text
    match over headline and summary, ranked by relevance with recency as
    the tie-break.

    A term can honestly be both: "Manchester" is a city and a word in
    stories about the club. Both halves are returned and the reader
    chooses; the server does not guess which was meant.
    """
    from app.search import MIN_QUERY_LEN, search

    if len(q.strip()) < MIN_QUERY_LEN:
        return {"query": q, "places": [], "events": [], "ambiguous": False}

    result = search(session, q, limit=limit)
    return {
        "query": q,
        # Several places answering to one name is a question, not an answer.
        # The client lists them; it must not silently take the first.
        "ambiguous": result.ambiguous,
        "places": [
            {
                "name": p.name,
                "lat": p.lat,
                "lon": p.lon,
                "country": p.country,
                "kind": p.kind,
                "context": p.context,
                "population": p.population,
            }
            for p in result.places
        ],
        "events": [
            {
                "id": r["id"],
                "source": r["source"],
                # The same shape the map and cluster list already receive. A
                # search result that is missing keywords or fetch time opens a
                # detail panel with holes in it, and the reader cannot tell
                # whether the hole is the data or the search.
                "source_event_id": r["source_event_id"],
                "category": r["category"],
                "severity": r["severity"],
                "keywords": r["keywords"],
                "country": r["country"],
                "lat": r["lat"],
                "lon": r["lon"],
                "occurred_at": r["occurred_at"].isoformat() if r["occurred_at"] else None,
                "fetched_at": r["fetched_at"].isoformat() if r["fetched_at"] else None,
                "payload": r["payload"],
            }
            for r in result.events
        ],
    }


@app.get("/scores")
def scores(
    session: Session = Depends(get_session),
    score_name: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    country: str | None = Query(default=None),
    limit: int = Query(default=API_DEFAULT_LIMIT, ge=1, le=API_MAX_LIMIT),
) -> list[dict]:
    stmt = select(ScoreRow).order_by(ScoreRow.bucket_start.desc()).limit(limit)
    if score_name is not None:
        stmt = stmt.where(ScoreRow.score_name == score_name)
    if since is not None:
        stmt = stmt.where(ScoreRow.bucket_start >= since)
    if country is not None:
        stmt = stmt.where(ScoreRow.country == country)
    return [_score_dict(r) for r in session.execute(stmt).scalars()]


def _story_payload(
    story: StoryRow,
    corro: StoryCorroborationRow | None,
    checks: dict[str, str],
    gist: StoryGistRow | None,
) -> dict:
    """One story as the API renders it — shared by /stories/top and
    /stories/developing so a pinned row and a list row never drift apart."""
    return {
        "id": str(story.id),
        "title": story.title,
        "first_seen": story.first_seen.isoformat(),
        "last_seen": story.last_seen.isoformat(),
        "member_count": story.member_count,
        "outlet_count": story.outlet_count,
        "owner_count": story.owner_count,
        "corroboration": corro.score if corro else None,
        "corroboration_components": corro.components if corro else None,
        "sensor_checks": checks,
        "method_version": story.method_version,
        "gist": gist.gist if gist else None,
        "category": gist.category if gist else None,
        "escalating": gist.escalating if gist else None,
    }


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

    gists: dict[int, StoryGistRow] = {}
    if story_ids:
        for g in session.execute(
            select(StoryGistRow).where(
                StoryGistRow.story_id.in_(story_ids),
                StoryGistRow.method_version == enrich.METHOD_VERSION,
            )
        ).scalars():
            gists[g.story_id] = g

    return [
        _story_payload(story, corro, checks.get(story.id, {}), gists.get(story.id))
        for story, corro in rows
    ]


#: One request cannot ask about an unbounded list of events. A map selection
#: is a screenful; anything larger is a different question.
MAX_STORY_LOOKUP_IDS = 500


@app.get("/stories/for-events")
def stories_for_events(
    session: Session = Depends(get_session),
    ids: str = Query(default="", description="Comma-separated event ids."),
) -> dict[str, dict]:
    """Which story, if any, each of these events belongs to (#782).

    A story opened from the map used to be an inspector — severity bar,
    coordinate provenance, raw payload — while the same story opened from the
    first page was the trust read and who said what. The difference was the
    surface, not the story.

    `story_members.event_id` is that table's primary key, so an event belongs
    to at most one story and this is a key hit per id. Events with no story
    are simply absent from the result: a GDELT record or a seismometer reading
    is telemetry, not news, and has no story view to open.

    The value is `_story_payload` unchanged, so a map row carries exactly what
    a first-page row carries and the two cannot drift apart.
    """
    from app.db_models import StoryMemberRow

    wanted: list[int] = []
    for part in ids.split(","):
        part = part.strip()
        if part.isdigit():
            wanted.append(int(part))
    if not wanted:
        return {}
    wanted = wanted[:MAX_STORY_LOOKUP_IDS]

    links = (
        session.execute(select(StoryMemberRow).where(StoryMemberRow.event_id.in_(wanted)))
        .scalars()
        .all()
    )
    if not links:
        return {}

    story_ids = {link.story_id for link in links}
    rows = session.execute(
        select(StoryRow, StoryCorroborationRow)
        .outerjoin(StoryCorroborationRow, StoryCorroborationRow.story_id == StoryRow.id)
        .where(StoryRow.id.in_(story_ids))
    ).all()

    checks: dict[int, dict[str, str]] = {}
    for check in session.execute(
        select(StorySensorCheckRow).where(StorySensorCheckRow.story_id.in_(story_ids))
    ).scalars():
        checks.setdefault(check.story_id, {})[check.claim_type] = check.verdict

    gists: dict[int, StoryGistRow] = {}
    for g in session.execute(
        select(StoryGistRow).where(
            StoryGistRow.story_id.in_(story_ids),
            StoryGistRow.method_version == enrich.METHOD_VERSION,
        )
    ).scalars():
        gists[g.story_id] = g

    payloads = {
        story.id: _story_payload(story, corro, checks.get(story.id, {}), gists.get(story.id))
        for story, corro in rows
    }
    return {
        str(link.event_id): payloads[link.story_id] for link in links if link.story_id in payloads
    }


@app.get("/stories/developing")
def stories_developing(
    session: Session = Depends(get_session),
    limit: int = Query(default=developing.DEFAULT_LIMIT, ge=1, le=10),
) -> list[dict]:
    """The Situation card's pinned slot (#449) — multi-day international
    stories still gathering coverage, best-first.

    Same row shape as /stories/top plus `pin_reasons`, the evidence for the
    pin: the card justifies a pin rather than asserting it. Corroboration
    rides along and is never a gate — a widely-told story with few
    independent owners is precisely what must stay visible.
    """
    picks = developing.select_developing(session, limit=limit)
    if not picks:
        return []

    order = {p["story_id"]: i for i, p in enumerate(picks)}
    reasons = {p["story_id"]: p["pin_reasons"] for p in picks}
    story_ids = list(order)

    stories = {
        story.id: (story, corro)
        for story, corro in session.execute(
            select(StoryRow, StoryCorroborationRow)
            .outerjoin(StoryCorroborationRow, StoryCorroborationRow.story_id == StoryRow.id)
            .where(StoryRow.id.in_(story_ids))
        ).all()
    }

    checks: dict[int, dict[str, str]] = {}
    for check in session.execute(
        select(StorySensorCheckRow).where(StorySensorCheckRow.story_id.in_(story_ids))
    ).scalars():
        checks.setdefault(check.story_id, {})[check.claim_type] = check.verdict

    gists: dict[int, StoryGistRow] = {}
    for g in session.execute(
        select(StoryGistRow).where(
            StoryGistRow.story_id.in_(story_ids),
            StoryGistRow.method_version == enrich.METHOD_VERSION,
        )
    ).scalars():
        gists[g.story_id] = g

    out = []
    for sid in sorted(order, key=lambda s: order[s]):
        if sid not in stories:
            continue
        story, corro = stories[sid]
        row = _story_payload(story, corro, checks.get(sid, {}), gists.get(sid))
        row["pin_reasons"] = reasons[sid]
        out.append(row)
    return out


def _bloc_contrast(members: list[dict]) -> dict[str, list[str]]:
    """What each origin-country bloc says that no other bloc does (#492).

    Deterministic: content terms (retrieval's stopword/term machinery) from
    each bloc's titles + summaries, minus every term any other bloc also
    uses — the actual wording difference behind the divergence score, not
    just who diverges. Empty when fewer than two blocs tell the story.
    """
    blocs: dict[str, Counter[str]] = {}
    for m in members:
        country = m.get("origin_country") or "??"
        text = f"{m.get('title') or ''} {m.get('summary') or ''}".lower()
        terms = {t for t in qa._TERM_RE.findall(text) if t not in qa._QUESTION_STOPWORDS}
        blocs.setdefault(country, Counter()).update(terms)
    if len(blocs) < 2:
        return {}
    out: dict[str, list[str]] = {}
    for country, counts in blocs.items():
        others: set[str] = set()
        for other_country, other_counts in blocs.items():
            if other_country != country:
                others |= set(other_counts)
        #: Stable order: strongest first, ties alphabetical.
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        distinct = [t for t, _ in ranked if t not in others][:5]
        if distinct:
            out[country] = distinct
    return out


#: A bloc leans a way only when that way clears this share of its labelled
#: articles; below it the lean is real but soft ("leans" not "mostly").
_TONE_STRONG_SHARE: float = 0.6


def _tone_lean(labels: list[str]) -> str:
    """A bloc's emotional lean from its members' VADER sentiment labels (#605).

    Deterministic and honest: a clear majority one way is "mostly", a plainer
    edge is "leans", an even positive/negative split is "mixed", and no signal
    is said plainly rather than guessed.
    """
    counts = Counter(labels)
    total = counts["negative"] + counts["positive"] + counts["neutral"]
    if total == 0:
        return "tone unclear"
    neg, pos = counts["negative"], counts["positive"]
    if neg > pos:
        return "mostly negative" if neg / total > _TONE_STRONG_SHARE else "leans negative"
    if pos > neg:
        return "mostly positive" if pos / total > _TONE_STRONG_SHARE else "leans positive"
    if neg > 0:  # equal and non-zero → genuinely split
        return "mixed"
    return "neutral"


def _framing_analysis(members: list[dict]) -> dict | None:
    """How each origin-country bloc frames the story, keyword + sentiment (#605).

    Structured, not prose: per bloc the article count, tone lean, and the
    wording only it uses (via `_bloc_contrast`); plus a synthesis naming the two
    loudest blocs' tones and signature terms. The frontend interpolates country
    names into these fields. None when fewer than two blocs tell the story.
    """
    contrast = _bloc_contrast(members)
    by_country: dict[str, list[dict]] = {}
    for m in members:
        by_country.setdefault(m.get("origin_country") or "??", []).append(m)
    if len(by_country) < 2:
        return None
    #: Loudest first (most articles), ties alphabetical — matches the groups list.
    order = sorted(by_country, key=lambda c: (-len(by_country[c]), c))
    blocs = [
        {
            "country": country,
            "articles": len(by_country[country]),
            "tone": _tone_lean(
                [m.get("sentiment") for m in by_country[country] if m.get("sentiment")]
            ),
            "terms": contrast.get(country, []),
        }
        for country in order
    ]
    a, b = blocs[0], blocs[1]
    synthesis = {
        "a": a["country"],
        "b": b["country"],
        "a_tone": a["tone"],
        "b_tone": b["tone"],
        "a_terms": a["terms"][:3],
        "b_terms": b["terms"][:3],
    }
    return {"blocs": blocs, "synthesis": synthesis}


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
    from app.sources.rss_registry import (
        content_owner_map,
        load_feed_configs,
        outlet_class_map,
        outlet_country_map,
    )

    owners = content_owner_map()
    origins = outlet_country_map()
    classes = outlet_class_map()
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
            "outlet_class": classes.get(event.source, "mainstream"),
            "url": (event.payload or {}).get("source_url") or (event.payload or {}).get("link"),
            "summary": (event.payload or {}).get("summary")
            or (event.payload or {}).get("description"),
            "sentiment": (event.payload or {}).get("sentiment_label"),
            "occurred_at": event.occurred_at.isoformat(),
            "similarity": member.similarity,
        }
        for member, event in rows
    ]


def _story_or_404(session: Session, story_id: int) -> StoryRow:
    story = session.get(StoryRow, story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="story not found")
    return story


def _story_members(session: Session, story_id: int) -> list[dict]:
    """Every member article of a story, with outlet + origin country (#448).

    Shared by the detail card and the deep read (#607) so both see the same
    member shape — title, summary, sentiment label, origin bloc, outlet class.
    """
    from app.db_models import StoryMemberRow
    from app.sources.rss_registry import (
        content_owner_map,
        load_feed_configs,
        outlet_class_map,
        outlet_country_map,
    )

    owners = content_owner_map()
    origins = outlet_country_map()
    classes = outlet_class_map()
    pretty = {cfg.source: cfg.pretty_name for cfg in load_feed_configs()}
    return [
        {
            "title": (event.payload or {}).get("title") or "",
            "source": event.source,
            "outlet": pretty.get(event.source, event.source),
            "owner": owners.get(event.source, event.source),
            "origin_country": origins.get(event.source),
            "outlet_class": classes.get(event.source, "mainstream"),
            "url": (event.payload or {}).get("source_url") or (event.payload or {}).get("link"),
            "summary": (event.payload or {}).get("summary")
            or (event.payload or {}).get("description"),
            "sentiment": (event.payload or {}).get("sentiment_label"),
            "occurred_at": event.occurred_at.isoformat(),
            "similarity": member.similarity,
        }
        for member, event in session.execute(
            select(StoryMemberRow, EventRow)
            .join(EventRow, EventRow.id == StoryMemberRow.event_id)
            .where(StoryMemberRow.story_id == story_id)
            .order_by(EventRow.occurred_at)
        ).all()
    ]


@app.get("/stories/{story_id}/detail")
def story_detail(
    story_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """The story pop-out card (#448): everything known about one story in one
    read — gist, corroboration evidence, contested-telling groups, sensor
    verdicts, and every member article with outlet + origin country."""
    from app.db_models import StoryDisagreementRow

    story = _story_or_404(session, story_id)

    corro = session.execute(
        select(StoryCorroborationRow).where(StoryCorroborationRow.story_id == story_id)
    ).scalar_one_or_none()
    disagreement = session.execute(
        select(StoryDisagreementRow).where(StoryDisagreementRow.story_id == story_id)
    ).scalar_one_or_none()
    gist = session.execute(
        select(StoryGistRow)
        .where(StoryGistRow.story_id == story_id)
        .order_by(StoryGistRow.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    checks = {
        c.claim_type: c.verdict
        for c in session.execute(
            select(StorySensorCheckRow).where(StorySensorCheckRow.story_id == story_id)
        ).scalars()
    }

    members = _story_members(session, story_id)

    return {
        "id": str(story.id),
        "title": story.title,
        "first_seen": story.first_seen.isoformat(),
        "last_seen": story.last_seen.isoformat(),
        "member_count": story.member_count,
        "outlet_count": story.outlet_count,
        "owner_count": story.owner_count,
        "gist": gist.gist if gist else None,
        "category": gist.category if gist else None,
        "escalating": gist.escalating if gist else None,
        "corroboration": corro.score if corro else None,
        "corroboration_components": corro.components if corro else None,
        "divergence": disagreement.divergence if disagreement else None,
        "divergence_groups": (disagreement.components or {}).get("groups", {})
        if disagreement
        else None,
        "sensor_checks": checks,
        "divergence_contrast": _bloc_contrast(members) if disagreement else None,
        "framing": _framing_analysis(members) if disagreement else None,
        "members": members,
    }


@app.post("/stories/{story_id}/deep-read")
def story_deep_read(story_id: int, session: Session = Depends(get_session)) -> dict:
    """The reasoned WHY behind a contested telling (#607), on demand.

    User-initiated, so it is RAM-gated like /brain/ask and returns a typed
    message at HTTP 200 on every failure. `analysis` is null when the story is
    not contested (one bloc) — the frontend only offers the button when the
    deterministic framing (#605) is present, so that path is a guard."""
    story = _story_or_404(session, story_id)
    if gate.qa_ram_blocked():
        return {"analysis": qa.BRAIN_BUSY_ANSWER}
    members = _story_members(session, story_id)
    framing = _framing_analysis(members)
    if framing is None:
        return {"analysis": None}
    blocs = deepread.deep_read_blocs(members, framing)
    prompt = deepread.build_deep_read_prompt(story.title, blocs)
    #: Plain text, not format=json (#609): the deep read is long prose, and a
    #: JSON wrapper truncated by num_predict is invalid JSON that raises on parse
    #: — read as "offline". Mirrors brain_ask_stream; a capped answer is just
    #: shorter valid prose.
    try:
        chunks = list(
            client.generate_text_stream(
                prompt,
                model=settings.qa_model,
                keep_alive="0",
                num_predict=deepread.DEEP_READ_NUM_PREDICT,
            )
        )
    except Exception:
        return {"analysis": qa.BRAIN_OFFLINE_ANSWER}
    text = "".join(chunks).strip()
    if not text:
        return {"analysis": qa.BRAIN_NOT_WORKING_ANSWER}
    #: Same plain-text + paragraph shaping as the ask answers (#480/#484/#598).
    return {"analysis": qa.reflow_paragraphs(qa.strip_markdown(text))}


@app.get("/disagreement/top")
def disagreement_top(
    session: Session = Depends(get_session),
    hours: int = Query(default=72, ge=1, le=24 * 30),
    limit: int = Query(default=10, ge=1, le=100),
) -> list[dict]:
    """Briefing (#398): the most contested tellings — stories whose country
    blocs word the same event most differently."""
    from app.db_models import StoryDisagreementRow

    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    rows = session.execute(
        select(StoryDisagreementRow, StoryRow.title)
        .join(StoryRow, StoryRow.id == StoryDisagreementRow.story_id)
        .where(StoryDisagreementRow.computed_at >= cutoff)
        .order_by(StoryDisagreementRow.divergence.desc())
        .limit(limit)
    ).all()
    return [
        {
            "story_id": str(row.story_id),
            "title": title,
            "divergence": row.divergence,
            "groups": (row.components or {}).get("groups", {}),
        }
        for row, title in rows
    ]


@app.get("/composite/movers")
def composite_movers(
    session: Session = Depends(get_session),
    limit: int = Query(default=8, ge=1, le=50),
) -> dict:
    """Briefing (#398): who moved most between the two latest scored months,
    plus the latest global mean for the plain-word status band."""
    months = (
        session.execute(
            select(ScoreRow.bucket_start)
            .where(ScoreRow.score_name == "composite")
            .distinct()
            .order_by(ScoreRow.bucket_start.desc())
            .limit(2)
        )
        .scalars()
        .all()
    )
    if not months:
        return {"latest_month": None, "global_mean": None, "movers": []}

    latest_month = months[0]
    latest = {
        row.country: row.score_value
        for row in session.execute(
            select(ScoreRow).where(
                ScoreRow.score_name == "composite", ScoreRow.bucket_start == latest_month
            )
        ).scalars()
    }
    previous = (
        {
            row.country: row.score_value
            for row in session.execute(
                select(ScoreRow).where(
                    ScoreRow.score_name == "composite", ScoreRow.bucket_start == months[1]
                )
            ).scalars()
        }
        if len(months) > 1
        else {}
    )
    movers = sorted(
        (
            {
                "country": country,
                "latest": value,
                "delta": value - previous[country],
            }
            for country, value in latest.items()
            if country in previous
        ),
        key=lambda m: -abs(m["delta"]),
    )[:limit]
    # Additive, so no existing consumer breaks: say when the numbers below
    # carry no information. The live composite returns 0.5 for every country
    # because retention deletes the history its rolling z-score needs (#586),
    # and a flat index rendered without comment reads as a real measurement
    # (#589).
    return {
        "latest_month": latest_month.strftime("%Y-%m-01"),
        "global_mean": sum(latest.values()) / len(latest) if latest else None,
        "movers": movers,
        "degenerate": composite_degeneracy.describe(
            list(latest.values()), label=f"composite {latest_month:%Y-%m}"
        ),
    }


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


@app.get("/brain/narrative/latest")
def brain_narrative_latest(session: Session = Depends(get_session)) -> dict:
    """The newest situation narrative (#409), or an explicit empty shape.

    The frontend uses `created_at` to decide when to render the card as stale
    ("brain resting") — backoff is visible, never a silent lie.
    """
    row = session.execute(
        select(BrainNarrativeRow).order_by(BrainNarrativeRow.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        return {"present": False, "payload": None, "model": None, "created_at": None}
    return {
        "present": True,
        "payload": row.payload,
        "model": row.model,
        "created_at": row.created_at.isoformat(),
    }


class AskExchange(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(default="", max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    #: Recent transcript turns (#444) — anchors vague follow-ups ("that", "it").
    history: list[AskExchange] = Field(default_factory=list, max_length=3)


def _ask_sources(stories: list[dict], sensors: list[dict] | None = None) -> list[dict]:
    """Numbered sources for the answer: stories first, then sensor readings.

    Sensors (#507) carry `story_id: None` — an instrument record has no story
    to open, so its (source) chip is a label rather than a link.
    """
    out = [
        {
            "n": s["n"],
            "story_id": s["story_id"],
            "title": s["title"],
            "outlets": s["sources"],
            "corroboration": s["corroboration"],
            "contested": s["contested"],
        }
        for s in stories
    ]
    out.extend(
        {
            "n": e["n"],
            "story_id": None,
            "title": e["headline"],
            "outlets": [e["source"]],
            "corroboration": None,
            "contested": False,
        }
        for e in (sensors or [])
    )
    return out


def _deechoed_answer(
    answer: str,
    *,
    qa_context: dict,
    question: str,
    history: list[dict],
) -> str:
    """One regeneration when the draft parrots the previous answer (#451).

    A retry failure keeps the echoing draft — an echo beats an error.
    """
    previous = str(history[-1].get("answer") or "") if history else ""
    if not previous or not qa.answer_echoes(previous, answer):
        return answer
    try:
        raw = client.generate_json(
            qa.build_echo_retry_prompt(qa_context, question, answer, previous),
            model=settings.qa_model,
            keep_alive="0",
        )
    except Exception:
        return answer
    retry = raw.get("answer") if isinstance(raw, dict) else None
    if isinstance(retry, str) and retry.strip() and not qa.answer_echoes(previous, retry):
        return retry.strip()
    return answer


def _derefused_answer(
    answer: str,
    *,
    qa_context: dict,
    question: str,
    stories: list[dict],
    sensors: list[dict] | None = None,
) -> str:
    """One regeneration when the model refuses despite relevant evidence (#467).

    Fires only when retrieval judged its stories plausibly relevant (#460) —
    an over-refusal, not an honest one. A failed or still-refusing retry keeps
    the refusal: refusal beats invention. The retry output goes through the
    same citation check chain as any draft.
    """
    if answer.strip() != qa.REFUSAL_ANSWER or not qa.has_relevant_evidence(stories, sensors):
        return answer
    try:
        raw = client.generate_json(
            qa.build_refusal_retry_prompt(qa_context, question),
            model=settings.qa_model,
            keep_alive="0",
        )
    except Exception:
        return answer
    retry = raw.get("answer") if isinstance(raw, dict) else None
    if isinstance(retry, str) and retry.strip():
        return retry.strip()
    return answer


def _extracted_answer(raw: object) -> str | None:
    """Usable answer string from a model response, else None (#474)."""
    answer = raw.get("answer") if isinstance(raw, dict) else None
    if isinstance(answer, str) and answer.strip():
        return answer
    return None


def _checked_ask_answer(
    *,
    answer: str,
    qa_context: dict,
    question: str,
    stories: list[dict],
    n_sources: int,
) -> str:
    #: Plain-text guard (#480) before the truncation guard (#474): flatten
    #: markdown first so the trim sees real sentences; a trimmed fragment must
    #: not keep a citation the surviving text no longer earns.
    answer = qa.strip_markdown(answer)
    answer = qa.trim_incomplete_tail(answer)
    answer = qa.strip_bad_citations(answer, n_sources)
    if not qa.citation_compliant(answer, n_sources):
        #: Grounded-but-uncited drafts keep their prose with the citation
        #: appended (#446) — cheaper and kinder than the repair/template path.
        salvaged = qa.attach_supported_citation(answer, stories)
        if salvaged is not None:
            answer = salvaged
    if not qa.citation_compliant(answer, n_sources):
        try:
            repaired = client.generate_json(
                qa.build_citation_repair_prompt(qa_context, question, answer),
                model=settings.qa_model,
                keep_alive="0",
            )
        except Exception:
            repaired = None
        repaired_answer = repaired.get("answer") if isinstance(repaired, dict) else None
        if isinstance(repaired_answer, str) and repaired_answer.strip():
            answer = qa.strip_bad_citations(repaired_answer, n_sources)
    if not qa.citation_compliant(answer, n_sources):
        answer = qa.build_no_evidence_answer(stories)
    #: Last step (#598): break the model's wall of text into short paragraphs.
    #: Runs after citation repair so appended [n] stays inside its paragraph.
    return qa.reflow_paragraphs(answer)


def _ask_payload(
    answer: str,
    digest: str | None,
    sources: list[dict],
    *,
    claims: list[dict] | None = None,
    reasoning: dict | None = None,
) -> dict:
    """Final ask response with the item-3 split (#413): a no-answer fallback
    means retrieval looked off-topic, so nothing may pose as the answer's
    sources — the retrieved stories move to `closest_matches` instead."""
    no_answer = answer.strip() == qa.NO_LOCAL_EVIDENCE_ANSWER
    return {
        "answer": answer,
        "context_digest": digest,
        "sources": [] if no_answer else sources,
        "closest_matches": sources if no_answer else [],
        #: (source)/(thinking) chip fuel (#476): per-sentence claim mapping —
        #: an unsupported sentence is the brain's own analysis — plus the
        #: retrieval reasoning the thinking popup shows.
        "claims": claims or [],
        "reasoning": reasoning,
    }


def _answer_annotations(
    session: Session,
    answer: str,
    stories: list[dict],
    trace: dict,
    sensors: list[dict] | None = None,
) -> tuple[list[dict], dict]:
    """Chip fuel for a final answer (#476): sentence→source claim mapping and
    a compact retrieval-reasoning summary for the thinking popup."""
    claims = qa.check_claims(answer, qa.support_texts(session, stories, sensors))["claims"]
    reasoning = {
        "method": trace.get("method"),
        "intents": trace.get("intents") or [],
        "terms": trace.get("terms") or [],
    }
    return claims, reasoning


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/brain/ask")
def brain_ask(req: AskRequest, session: Session = Depends(get_session)) -> dict:
    """Answer a question grounded in the live data (#411).

    User-initiated and synchronous, so it does NOT back off on every running job
    the way the scheduled narrative does — it refuses only when RAM is genuinely
    low, to protect the Pi from OOM. Every failure returns a typed answer at HTTP
    200; only a bad request is a 422.
    """
    if gate.qa_ram_blocked():
        return _ask_payload(qa.BRAIN_BUSY_ANSWER, None, [])
    history = [h.model_dump() for h in req.history]
    #: Elaborate mode (#600): the reader asked to explain/go deeper — swap in the
    #: ELI10 prompt, raise the token cap, and skip the echo guard (elaboration
    #: legitimately expands the previous answer, which the guard would reject).
    elaborate = qa.is_elaborate_request(req.question)
    num_predict = qa.ELABORATE_NUM_PREDICT if elaborate else None
    trace: dict = {}
    qa_context = qa.build_qa_context(session, question=req.question, history=history, trace=trace)
    prompt = qa.build_qa_prompt(qa_context, req.question, history=history, elaborate=elaborate)
    try:
        answer = _extracted_answer(
            client.generate_json(
                prompt, model=settings.qa_model, keep_alive="0", num_predict=num_predict
            )
        )
    except Exception:
        return _ask_payload(qa.BRAIN_OFFLINE_ANSWER, None, [])
    if answer is None:
        #: One retry on unusable output (#474) — 3/12 audit answers died here.
        try:
            answer = _extracted_answer(
                client.generate_json(
                    prompt, model=settings.qa_model, keep_alive="0", num_predict=num_predict
                )
            )
        except Exception:
            answer = None
    if answer is None:
        return _ask_payload(qa.BRAIN_NOT_WORKING_ANSWER, None, [])
    stories = qa_context.get("stories") or []
    sensors = qa_context.get("sensors") or []
    sources = _ask_sources(stories, sensors)
    if not elaborate:
        answer = _deechoed_answer(
            answer, qa_context=qa_context, question=req.question, history=history
        )
    answer = _derefused_answer(
        answer, qa_context=qa_context, question=req.question, stories=stories, sensors=sensors
    )
    answer = _checked_ask_answer(
        answer=answer,
        qa_context=qa_context,
        question=req.question,
        stories=stories,
        n_sources=len(sources),
    )
    claims, reasoning = _answer_annotations(session, answer, stories, trace, sensors)
    return _ask_payload(
        answer, context.input_digest(qa_context), sources, claims=claims, reasoning=reasoning
    )


@app.post("/brain/ask/stream")
def brain_ask_stream(req: AskRequest, session: Session = Depends(get_session)) -> StreamingResponse:
    """Stream ask-the-brain answer chunks, then a citation-checked final answer."""

    def gen() -> Iterator[str]:
        if gate.qa_ram_blocked():
            yield _sse("final", _ask_payload(qa.BRAIN_BUSY_ANSWER, None, []))
            return
        history = [h.model_dump() for h in req.history]
        elaborate = qa.is_elaborate_request(req.question)  # #600
        num_predict = qa.ELABORATE_NUM_PREDICT if elaborate else None
        trace: dict = {}
        qa_context = qa.build_qa_context(
            session, question=req.question, history=history, trace=trace
        )
        stories = qa_context.get("stories") or []
        sensors = qa_context.get("sensors") or []
        sources = _ask_sources(stories, sensors)
        digest = context.input_digest(qa_context)
        yield _sse("sources", {"context_digest": digest, "sources": sources})
        chunks: list[str] = []
        try:
            prompt = qa.build_qa_text_prompt(
                qa_context, req.question, history=history, elaborate=elaborate
            )
            for chunk in client.generate_text_stream(
                prompt, model=settings.qa_model, keep_alive="0", num_predict=num_predict
            ):
                chunks.append(chunk)
                yield _sse("delta", {"text": chunk})
        except Exception:
            yield _sse("final", _ask_payload(qa.BRAIN_OFFLINE_ANSWER, None, []))
            return
        answer = "".join(chunks).strip()
        if not answer:
            #: One non-stream retry when the stream produced nothing (#474).
            try:
                retried = _extracted_answer(
                    client.generate_json(
                        qa.build_qa_prompt(
                            qa_context, req.question, history=history, elaborate=elaborate
                        ),
                        model=settings.qa_model,
                        keep_alive="0",
                        num_predict=num_predict,
                    )
                )
            except Exception:
                retried = None
            answer = retried if retried is not None else qa.BRAIN_NOT_WORKING_ANSWER
        if answer != qa.BRAIN_NOT_WORKING_ANSWER:
            if not elaborate:
                answer = _deechoed_answer(
                    answer, qa_context=qa_context, question=req.question, history=history
                )
            answer = _derefused_answer(
                answer,
                qa_context=qa_context,
                question=req.question,
                stories=stories,
                sensors=sensors,
            )
            answer = _checked_ask_answer(
                answer=answer,
                qa_context=qa_context,
                question=req.question,
                stories=stories,
                n_sources=len(sources),
            )
        claims, reasoning = _answer_annotations(session, answer, stories, trace, sensors)
        yield _sse(
            "final", _ask_payload(answer, digest, sources, claims=claims, reasoning=reasoning)
        )

    return StreamingResponse(gen(), media_type="text/event-stream")


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
    path = exports_dir() / filename
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


@app.get("/audit/latest")
def audit_latest(
    session: Session = Depends(get_session),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict:
    """The most recent completed source-data audit, and whether it moved (#692).

    #669 gave the audit a clock and a history, and nothing read it. Two of its
    nine findings started the work that became #681, #682, #684, #689, #690 and
    #691 — found by running a script by hand and reading a terminal.

    `present: false` when the audit has never completed. That is deliberately
    distinct from a run that found nothing: "clean" and "never ran" looking the
    same is the #663 failure shape, and a zero here would read as a clean bill
    of health the system has not earned.

    `previous_findings_total` and `delta` compare against the previous
    *completed* run, the same rule the notifier uses — a crashed run never
    reached most sources, so diffing against it invents movement.
    """
    runs = (
        session.execute(
            select(AuditRunRow)
            .where(AuditRunRow.finished_at.is_not(None))
            .order_by(AuditRunRow.started_at.desc())
            .limit(2)
        )
        .scalars()
        .all()
    )
    if not runs:
        return {
            "present": False,
            "started_at": None,
            "sources_measured": None,
            "findings_total": None,
            "previous_findings_total": None,
            "delta": None,
            "findings": [],
        }

    latest = runs[0]
    previous = runs[1] if len(runs) > 1 else None
    rows = (
        session.execute(
            select(AuditFindingRow)
            .where(AuditFindingRow.run_id == latest.id)
            .order_by(AuditFindingRow.check_name, AuditFindingRow.source)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return {
        "present": True,
        "started_at": latest.started_at.isoformat() if latest.started_at else None,
        "sources_measured": latest.sources_measured,
        "findings_total": latest.findings_total,
        "previous_findings_total": previous.findings_total if previous else None,
        "delta": (latest.findings_total - previous.findings_total) if previous else None,
        "findings": [{"source": r.source, "check": r.check_name, "detail": r.detail} for r in rows],
    }
