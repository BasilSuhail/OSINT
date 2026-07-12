"""The brain's snapshot builder (#409).

Feeds the model pre-digested numbers, never raw rows, so the prompt stays tiny
(num_ctx 2048) and cheap on the Pi. The snapshot spans the world signal (top
stories) and the system itself (job outcomes, ingest freshness).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db_models import IngestHealthRow, JobRunRow, StoryRow

_TOP_STORIES: int = 5
_STORY_WINDOW_H: int = 24
_JOB_WINDOW_H: int = 6


def build_snapshot(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    story_cut = now - timedelta(hours=_STORY_WINDOW_H)
    job_cut = now - timedelta(hours=_JOB_WINDOW_H)

    stories = (
        session.execute(
            select(StoryRow)
            .where(StoryRow.last_seen >= story_cut)
            .order_by(StoryRow.outlet_count.desc(), StoryRow.member_count.desc())
            .limit(_TOP_STORIES)
        )
        .scalars()
        .all()
    )

    job_counts = dict(
        session.execute(
            select(JobRunRow.status, func.count())
            .where(JobRunRow.started_at >= job_cut)
            .group_by(JobRunRow.status)
        ).all()
    )

    freshest = session.execute(select(func.max(IngestHealthRow.last_success))).scalar_one_or_none()

    return {
        "as_of": now.isoformat(),
        "top_stories": [
            {
                "title": s.title,
                "outlets": s.outlet_count,
                "members": s.member_count,
            }
            for s in stories
        ],
        "jobs": {
            "done": int(job_counts.get("done", 0)),
            "running": int(job_counts.get("running", 0)),
            "failed": int(job_counts.get("failed", 0)),
        },
        "ingest_last_success": freshest.isoformat() if freshest else None,
    }


def input_digest(snapshot: dict[str, Any]) -> str:
    blob = json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def build_prompt(snapshot: dict[str, Any]) -> str:
    return (
        "You are the situational-awareness brain of an OSINT early-warning "
        "system. Below is a JSON snapshot of the current world signal and the "
        "system's own health. Describe ONLY what the numbers show. Invent no "
        "facts, names, places, or events not present in the snapshot.\n\n"
        "Return a JSON object with exactly these keys:\n"
        '  "headline": one short sentence, the single most important thing now.\n'
        '  "world": 2-4 sentences on the story signal.\n'
        '  "system": 1-2 sentences on pipeline health (jobs, ingest freshness).\n'
        '  "watch": array of 0-3 short strings to keep an eye on.\n\n'
        f"SNAPSHOT:\n{json.dumps(snapshot, ensure_ascii=False)}"
    )
