"""The brain's Q&A layer (#411).

Builds a compact context = the Phase 1 situation snapshot plus three lightweight
headline facts (latest composite + highest-stress country, most-contested story,
the prediction scoreboard's graded/total counts), then a no-fabrication prompt.
Reuses everything from Phase 1; adds only cheap headline reads.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.brain import context, enrich
from app.db_models import (
    EventRow,
    PredictionRow,
    ScoreRow,
    StoryCorroborationRow,
    StoryDisagreementRow,
    StoryGistRow,
    StoryMemberRow,
    StoryRow,
    StorySensorCheckRow,
)


def _latest_composite(session: Session) -> dict[str, Any] | None:
    latest = session.execute(
        select(func.max(ScoreRow.bucket_start)).where(ScoreRow.score_name == "composite")
    ).scalar_one_or_none()
    if latest is None:
        return None
    mean = session.execute(
        select(func.avg(ScoreRow.score_value)).where(
            ScoreRow.score_name == "composite", ScoreRow.bucket_start == latest
        )
    ).scalar_one()
    top = session.execute(
        select(ScoreRow.country, ScoreRow.score_value)
        .where(ScoreRow.score_name == "composite", ScoreRow.bucket_start == latest)
        .order_by(ScoreRow.score_value.desc())
        .limit(1)
    ).first()
    return {
        "latest_month": latest.isoformat(),
        "global_mean": round(float(mean), 3) if mean is not None else None,
        "highest_stress": ({"country": top[0], "score": round(float(top[1]), 3)} if top else None),
    }


def _most_contested(session: Session) -> dict[str, Any] | None:
    row = session.execute(
        select(StoryDisagreementRow.divergence, StoryRow.title)
        .join(StoryRow, StoryRow.id == StoryDisagreementRow.story_id)
        .order_by(StoryDisagreementRow.divergence.desc())
        .limit(1)
    ).first()
    return {"title": row[1], "divergence": round(float(row[0]), 3)} if row else None


def _scoreboard(session: Session) -> dict[str, int]:
    graded = session.execute(
        select(func.count()).select_from(PredictionRow).where(PredictionRow.outcome.is_not(None))
    ).scalar_one()
    total = session.execute(select(func.count()).select_from(PredictionRow)).scalar_one()
    return {"graded": int(graded), "total": int(total)}


#: divergence at or above this = a contested story (tellers disagree sharply).
CONTESTED_THRESHOLD: float = 0.5
_QA_STORIES: int = 6
_QA_WINDOW_H: int = 72
_MAX_OUTLETS: int = 3


def build_qa_stories(
    session: Session, *, limit: int = _QA_STORIES, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Top `limit` loudest recent stories, each provenance-tagged with the trust
    signals we already compute (corroboration, contested, sensor) + outlet sources."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=_QA_WINDOW_H)
    rows = session.execute(
        select(StoryRow, StoryCorroborationRow)
        .outerjoin(StoryCorroborationRow, StoryCorroborationRow.story_id == StoryRow.id)
        .where(StoryRow.last_seen >= cutoff)
        .order_by(StoryRow.outlet_count.desc(), StoryRow.member_count.desc())
        .limit(limit)
    ).all()
    story_ids = [s.id for s, _ in rows]
    if not story_ids:
        return []

    gists = {
        g.story_id: g.gist
        for g in session.execute(
            select(StoryGistRow).where(
                StoryGistRow.story_id.in_(story_ids),
                StoryGistRow.method_version == enrich.METHOD_VERSION,
            )
        ).scalars()
    }
    divs: dict[int, float] = {}
    for sid, div in session.execute(
        select(StoryDisagreementRow.story_id, StoryDisagreementRow.divergence).where(
            StoryDisagreementRow.story_id.in_(story_ids)
        )
    ).all():
        divs[sid] = max(divs.get(sid, 0.0), float(div))
    sensors: dict[int, dict[str, str]] = {}
    for c in session.execute(
        select(StorySensorCheckRow).where(StorySensorCheckRow.story_id.in_(story_ids))
    ).scalars():
        sensors.setdefault(c.story_id, {})[c.claim_type] = c.verdict

    from app.sources.rss_registry import load_feed_configs

    pretty = {cfg.source: cfg.pretty_name for cfg in load_feed_configs()}

    out: list[dict[str, Any]] = []
    for i, (story, corro) in enumerate(rows, 1):
        srcs = (
            session.execute(
                select(EventRow.source)
                .join(StoryMemberRow, StoryMemberRow.event_id == EventRow.id)
                .where(StoryMemberRow.story_id == story.id)
                .distinct()
                .limit(_MAX_OUTLETS)
            )
            .scalars()
            .all()
        )
        div = divs.get(story.id)
        out.append(
            {
                "n": i,
                "story_id": story.id,
                "title": story.title,
                "gist": gists.get(story.id),
                "corroboration": round(float(corro.score), 3) if corro else None,
                "outlet_count": story.outlet_count,
                "owner_count": story.owner_count,
                "divergence": round(div, 3) if div is not None else None,
                "contested": bool(div is not None and div >= CONTESTED_THRESHOLD),
                "sensor": sensors.get(story.id, {}),
                "sources": [pretty.get(s, s) for s in srcs],
            }
        )
    return out


def build_qa_context(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    snapshot = context.build_snapshot(session, now=now)
    return {
        **snapshot,
        "latest_composite": _latest_composite(session),
        "most_contested": _most_contested(session),
        "scoreboard": _scoreboard(session),
        "stories": build_qa_stories(session, now=now),
    }


def build_qa_prompt(qa_context: dict[str, Any], question: str) -> str:
    return (
        "You are the Q&A brain of an OSINT early-warning system. Answer the user's "
        "question using ONLY the JSON context below. If the context does not contain "
        "the answer, reply exactly: I don't have data on that. Invent no facts, names, "
        "places, or numbers not present in the context.\n\n"
        'Return a JSON object with exactly one key: "answer" (a short plain-English '
        "string).\n\n"
        f"CONTEXT:\n{json.dumps(qa_context, ensure_ascii=False)}\n\n"
        f"QUESTION: {question}"
    )
