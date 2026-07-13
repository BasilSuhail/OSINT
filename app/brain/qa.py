"""The brain's Q&A layer (#411).

Builds a compact context = the Phase 1 situation snapshot plus three lightweight
headline facts (latest composite + highest-stress country, most-contested story,
the prediction scoreboard's graded/total counts), then a no-fabrication prompt.
Reuses everything from Phase 1; adds only cheap headline reads.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.brain import context
from app.db_models import PredictionRow, ScoreRow, StoryDisagreementRow, StoryRow


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


def build_qa_context(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    snapshot = context.build_snapshot(session, now=now)
    return {
        **snapshot,
        "latest_composite": _latest_composite(session),
        "most_contested": _most_contested(session),
        "scoreboard": _scoreboard(session),
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
