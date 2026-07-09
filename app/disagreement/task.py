"""Disagreement worker body — divergence rows for stories in the rolling window.

For every story still inside the clustering window with members from at least
two known-origin countries, compute the disagreement-v1.0 divergence
(`app.disagreement.tellings`) and upsert it. Called by the 30-minute beat
task in `app.tasks` and by `make disagreement`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_engine
from app.db_models import EventRow, StoryDisagreementRow, StoryMemberRow, StoryRow
from app.disagreement.tellings import METHOD_VERSION, story_divergence
from app.sources.rss_registry import outlet_country_map
from app.stories.task import WINDOW_HOURS


def _disagreement_body(*, now: datetime | None = None) -> dict[str, Any]:
    from app.jobs.heartbeat import job_run

    factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    with job_run("disagreement", session_factory=factory):
        return _disagreement_inner(now=now)


def _disagreement_inner(*, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=WINDOW_HOURS)
    country_map = outlet_country_map()
    counters = {"stories": 0, "scored": 0, "single_group": 0}

    with Session(get_engine()) as session:
        stories = (
            session.execute(select(StoryRow).where(StoryRow.last_seen >= cutoff)).scalars().all()
        )
        for story in stories:
            counters["stories"] += 1
            member_rows = session.execute(
                select(EventRow.payload, EventRow.source)
                .join(StoryMemberRow, StoryMemberRow.event_id == EventRow.id)
                .where(StoryMemberRow.story_id == story.id)
            ).all()
            members = [
                {"title": (payload or {}).get("title") or "", "source": source}
                for payload, source in member_rows
            ]
            result = story_divergence(members, country_map=country_map)
            if result is None:
                counters["single_group"] += 1
                continue

            existing = session.execute(
                select(StoryDisagreementRow).where(
                    StoryDisagreementRow.story_id == story.id,
                    StoryDisagreementRow.method_version == METHOD_VERSION,
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    StoryDisagreementRow(
                        story_id=story.id,
                        divergence=result["divergence"],
                        components=result["components"],
                        method_version=METHOD_VERSION,
                        computed_at=now,
                    )
                )
            else:
                existing.divergence = result["divergence"]
                existing.components = result["components"]
                existing.computed_at = now
            counters["scored"] += 1

        session.commit()

    return counters
