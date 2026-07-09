"""Story clustering worker body — cluster the rolling news window.

Loads unassigned news events from the last WINDOW_HOURS, rebuilds existing
story centroids from members still in the window, runs the pure clusterer,
and persists new stories + memberships. Called by the 30-minute beat task in
`app.tasks` and by `make stories`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_engine
from app.db_models import EventRow, StoryMemberRow, StoryRow
from app.sources.rss_registry import content_owner_map
from app.stories.cluster import cluster_articles

WINDOW_HOURS: int = 72


def _cluster_stories_body(*, now: datetime | None = None) -> dict[str, Any]:
    from app.jobs.heartbeat import job_run

    factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    with job_run("stories-cluster", session_factory=factory):
        return _cluster_stories_inner(now=now)


def _cluster_stories_inner(*, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=WINDOW_HOURS)

    with Session(get_engine()) as session:
        news = session.execute(
            select(EventRow.id, EventRow.source, EventRow.occurred_at, EventRow.payload).where(
                EventRow.category == "news", EventRow.occurred_at >= cutoff
            )
        ).all()
        assigned_rows = session.execute(
            select(StoryMemberRow.event_id, StoryMemberRow.story_id).where(
                StoryMemberRow.event_id.in_([row.id for row in news] or [0])
            )
        ).all()
        assigned = {row.event_id: row.story_id for row in assigned_rows}

        articles = [
            {
                "event_id": row.id,
                "title": (row.payload or {}).get("title") or "",
                "source": row.source,
                "occurred_at": row.occurred_at,
            }
            for row in news
            if row.id not in assigned
        ]
        existing = [
            {
                "event_id": row.id,
                "story_id": assigned[row.id],
                "title": (row.payload or {}).get("title") or "",
            }
            for row in news
            if row.id in assigned
        ]

        owner_map = content_owner_map()
        result = cluster_articles(articles, existing=existing, owner_map=owner_map)

        # Persist new stories first so members can reference their ids.
        new_story_ids: list[int] = []
        for story in result.new_stories:
            row = StoryRow(**story)
            session.add(row)
            session.flush()
            new_story_ids.append(row.id)

        touched_existing: set[int] = set()
        for member in result.new_members:
            story_id = (
                member["story_id"]
                if member["story_id"] is not None
                else new_story_ids[member["story_index"]]
            )
            if member["story_id"] is not None:
                touched_existing.add(story_id)
            session.add(
                StoryMemberRow(
                    event_id=member["event_id"],
                    story_id=story_id,
                    similarity=member["similarity"],
                )
            )

        # Refresh counters on existing stories that gained members.
        for story_id in touched_existing:
            members = session.execute(
                select(StoryMemberRow.event_id).where(StoryMemberRow.story_id == story_id)
            ).scalars()
            event_ids = list(members)
            sources = session.execute(
                select(EventRow.source, EventRow.occurred_at).where(EventRow.id.in_(event_ids))
            ).all()
            story = session.get(StoryRow, story_id)
            if story is not None and sources:
                story.member_count = len(event_ids)
                story.outlet_count = len({s.source for s in sources})
                story.owner_count = len({owner_map.get(s.source, s.source) for s in sources})
                story.last_seen = max(s.occurred_at for s in sources)

        session.commit()

        return {
            "window_news": len(news),
            "newly_assigned": len(result.new_members),
            "new_stories": len(result.new_stories),
            "joined_existing": len(touched_existing),
        }
