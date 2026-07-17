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
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.brain import client, context, enrich, gate, qa
from app.db import get_session_factory
from app.db_models import (
    BrainNarrativeRow,
    EventRow,
    IngestHealthRow,
    JobRunRow,
    PredictionRow,
    ScoreRow,
    StoryCorroborationRow,
    StoryGistRow,
    StoryRow,
    StorySensorCheckRow,
)
from app.events_bus import subscribe_new_events
from app.journal.scoreboard import build_scoreboard
from app.settings import settings

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
    limit: int = Query(default=API_DEFAULT_LIMIT, ge=1, le=API_MAX_LIMIT),
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
            "gist": gists[story.id].gist if story.id in gists else None,
            "category": gists[story.id].category if story.id in gists else None,
            "escalating": gists[story.id].escalating if story.id in gists else None,
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


@app.get("/stories/{story_id}/detail")
def story_detail(
    story_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """The story pop-out card (#448): everything known about one story in one
    read — gist, corroboration evidence, contested-telling groups, sensor
    verdicts, and every member article with outlet + origin country."""
    from app.db_models import StoryDisagreementRow, StoryMemberRow
    from app.sources.rss_registry import content_owner_map, load_feed_configs, outlet_country_map

    story = session.get(StoryRow, story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="story not found")

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

    owners = content_owner_map()
    origins = outlet_country_map()
    pretty = {cfg.source: cfg.pretty_name for cfg in load_feed_configs()}
    members = [
        {
            "title": (event.payload or {}).get("title") or "",
            "source": event.source,
            "outlet": pretty.get(event.source, event.source),
            "owner": owners.get(event.source, event.source),
            "origin_country": origins.get(event.source),
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
        "members": members,
    }


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
    return {
        "latest_month": latest_month.strftime("%Y-%m-01"),
        "global_mean": sum(latest.values()) / len(latest) if latest else None,
        "movers": movers,
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


def _ask_sources(stories: list[dict]) -> list[dict]:
    return [
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


def _checked_ask_answer(
    *,
    answer: str,
    qa_context: dict,
    question: str,
    stories: list[dict],
    n_sources: int,
) -> str:
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
    return answer


def _ask_payload(answer: str, digest: str | None, sources: list[dict]) -> dict:
    """Final ask response with the item-3 split (#413): a no-answer fallback
    means retrieval looked off-topic, so nothing may pose as the answer's
    sources — the retrieved stories move to `closest_matches` instead."""
    no_answer = answer.strip() == qa.NO_LOCAL_EVIDENCE_ANSWER
    return {
        "answer": answer,
        "context_digest": digest,
        "sources": [] if no_answer else sources,
        "closest_matches": sources if no_answer else [],
    }


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
    if gate.ram_free_mb() < settings.qa_min_free_mb:
        return _ask_payload(
            "Brain busy — the box is loaded right now, try again in a moment.", None, []
        )
    history = [h.model_dump() for h in req.history]
    qa_context = qa.build_qa_context(session, question=req.question, history=history)
    try:
        raw = client.generate_json(
            qa.build_qa_prompt(qa_context, req.question, history=history),
            model=settings.qa_model,
            keep_alive="0",
        )
    except Exception:
        return _ask_payload("The brain is offline right now.", None, [])
    answer = raw.get("answer") if isinstance(raw, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        return _ask_payload("The brain is not working right now.", None, [])
    stories = qa_context.get("stories") or []
    sources = _ask_sources(stories)
    answer = _deechoed_answer(answer, qa_context=qa_context, question=req.question, history=history)
    answer = _checked_ask_answer(
        answer=answer,
        qa_context=qa_context,
        question=req.question,
        stories=stories,
        n_sources=len(sources),
    )
    return _ask_payload(answer, context.input_digest(qa_context), sources)


@app.post("/brain/ask/stream")
def brain_ask_stream(req: AskRequest, session: Session = Depends(get_session)) -> StreamingResponse:
    """Stream ask-the-brain answer chunks, then a citation-checked final answer."""

    def gen() -> Iterator[str]:
        if gate.ram_free_mb() < settings.qa_min_free_mb:
            yield _sse(
                "final",
                _ask_payload(
                    "Brain busy — the box is loaded right now, try again in a moment.", None, []
                ),
            )
            return
        history = [h.model_dump() for h in req.history]
        qa_context = qa.build_qa_context(session, question=req.question, history=history)
        stories = qa_context.get("stories") or []
        sources = _ask_sources(stories)
        digest = context.input_digest(qa_context)
        yield _sse("sources", {"context_digest": digest, "sources": sources})
        chunks: list[str] = []
        try:
            prompt = qa.build_qa_text_prompt(qa_context, req.question, history=history)
            for chunk in client.generate_text_stream(
                prompt, model=settings.qa_model, keep_alive="0"
            ):
                chunks.append(chunk)
                yield _sse("delta", {"text": chunk})
        except Exception:
            yield _sse("final", _ask_payload("The brain is offline right now.", None, []))
            return
        answer = "".join(chunks).strip()
        if not answer:
            answer = "The brain is not working right now."
        else:
            answer = _deechoed_answer(
                answer, qa_context=qa_context, question=req.question, history=history
            )
            answer = _checked_ask_answer(
                answer=answer,
                qa_context=qa_context,
                question=req.question,
                stories=stories,
                n_sources=len(sources),
            )
        yield _sse("final", _ask_payload(answer, digest, sources))

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
