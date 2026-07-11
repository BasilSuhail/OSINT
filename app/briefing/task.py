"""Briefing worker body — gather the week from live tables, render, export.

Called by the Monday-morning beat in `app.tasks` (analytics queue — one heavy
job at a time) and by `make briefing`. The markdown is the newsletter body;
the JSON is the machine-readable artifact of record.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.briefing.render import render_markdown
from app.db import get_engine
from app.db_models import (
    PredictionRow,
    ScoreRow,
    StoryCorroborationRow,
    StoryDisagreementRow,
    StoryRow,
    StorySensorCheckRow,
)
from app.journal.scoreboard import build_scoreboard

WEEK_DAYS: int = 7
TOP_N: int = 5
MOVERS_N: int = 6

#: Same bands as the dashboard's stressBand — one vocabulary everywhere.
_BANDS: tuple[tuple[float, str], ...] = ((0.7, "high stress"), (0.55, "elevated"), (0.0, "calm"))


def _stress_word(mean: float) -> str:
    for threshold, word in _BANDS:
        if mean >= threshold:
            return word
    return "calm"


def _briefing_body(*, now: datetime | None = None) -> dict[str, Any]:
    from app.jobs.heartbeat import job_run

    factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    with job_run("briefing", session_factory=factory):
        return _briefing_inner(now=now)


def _briefing_inner(*, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    week_start = now - timedelta(days=WEEK_DAYS)

    with Session(get_engine()) as session:
        briefing = {
            "week_start": week_start.date().isoformat(),
            "week_end": now.date().isoformat(),
            "stress": _stress(session),
            "movers": _movers(session),
            "top_stories": _top_stories(session, week_start),
            "contested": _contested(session, week_start),
            "scoreboard": _scoreboard(session),
        }

    markdown = render_markdown(briefing)
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "weekly-briefing.md").write_text(markdown)
    (exports / "weekly-briefing.json").write_text(
        json.dumps({"generated_at": now.isoformat(), **briefing}, indent=2) + "\n"
    )

    return {
        "top_stories": len(briefing["top_stories"]),
        "contested": len(briefing["contested"]),
        "movers": len(briefing["movers"]),
        "scoreboard_lines": len(briefing["scoreboard"]),
    }


def _latest_months(session: Session) -> list[datetime]:
    return list(
        session.execute(
            select(ScoreRow.bucket_start)
            .where(ScoreRow.score_name == "composite")
            .distinct()
            .order_by(ScoreRow.bucket_start.desc())
            .limit(2)
        ).scalars()
    )


def _month_scores(session: Session, month: datetime) -> dict[str, float]:
    return {
        row.country: row.score_value
        for row in session.execute(
            select(ScoreRow).where(
                ScoreRow.score_name == "composite", ScoreRow.bucket_start == month
            )
        ).scalars()
    }


def _stress(session: Session) -> dict[str, Any]:
    months = _latest_months(session)
    if not months:
        return {"word": "no data", "mean": 0.0, "month": "—"}
    latest = _month_scores(session, months[0])
    mean = sum(latest.values()) / len(latest) if latest else 0.0
    return {"word": _stress_word(mean), "mean": mean, "month": months[0].strftime("%Y-%m")}


def _movers(session: Session) -> list[dict[str, Any]]:
    months = _latest_months(session)
    if len(months) < 2:
        return []
    latest = _month_scores(session, months[0])
    previous = _month_scores(session, months[1])
    movers = sorted(
        (
            {"country": country, "latest": value, "delta": value - previous[country]}
            for country, value in latest.items()
            # A zero delta is not a mover — rendering ▼ 0.00 would mislead.
            if country in previous and abs(value - previous[country]) > 1e-9
        ),
        key=lambda m: -abs(m["delta"]),
    )
    return movers[:MOVERS_N]


def _top_stories(session: Session, since: datetime) -> list[dict[str, Any]]:
    rows = session.execute(
        select(StoryRow, StoryCorroborationRow)
        .join(StoryCorroborationRow, StoryCorroborationRow.story_id == StoryRow.id)
        .where(StoryRow.last_seen >= since, StoryCorroborationRow.score > 0)
        .order_by(StoryCorroborationRow.score.desc())
        .limit(TOP_N)
    ).all()
    out = []
    for story, corro in rows:
        confirmed = list(
            session.execute(
                select(StorySensorCheckRow.claim_type).where(
                    StorySensorCheckRow.story_id == story.id,
                    StorySensorCheckRow.verdict == "confirmed",
                )
            ).scalars()
        )
        out.append(
            {
                "title": story.title,
                "owner_count": story.owner_count,
                "corroboration": corro.score,
                "confirmed": confirmed,
            }
        )
    return out


def _contested(session: Session, since: datetime) -> list[dict[str, Any]]:
    rows = session.execute(
        select(StoryDisagreementRow, StoryRow.title)
        .join(StoryRow, StoryRow.id == StoryDisagreementRow.story_id)
        .where(StoryDisagreementRow.computed_at >= since)
        .order_by(StoryDisagreementRow.divergence.desc())
        .limit(TOP_N)
    ).all()
    return [
        {
            "title": title,
            "divergence": row.divergence,
            "groups": (row.components or {}).get("groups", {}),
        }
        for row, title in rows
    ]


def _scoreboard(session: Session) -> list[dict[str, Any]]:
    predictions = [
        {
            "source": row.source,
            "method_version": row.method_version,
            "horizon_months": row.horizon_months,
            "score": row.score,
            "outcome": row.outcome,
        }
        for row in session.execute(select(PredictionRow)).scalars()
    ]
    return [
        {
            "source": line["source"],
            "horizon_months": line["horizon_months"],
            "issued": line["issued"],
            "graded": line["graded"],
            "pending": line["pending"],
            "brier": line["brier"],
        }
        for line in build_scoreboard(predictions)
    ]
