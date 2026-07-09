"""Disagreement worker body — divergence rows for stories in the rolling window.

For every story still inside the clustering window with members from at least
two known-origin countries, compute the disagreement-v1.0 divergence
(`app.disagreement.tellings`) and upsert it. Called by the 30-minute beat
task in `app.tasks` and by `make disagreement`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_engine
from app.db_models import (
    DisagreementPairRow,
    EventRow,
    StoryDisagreementRow,
    StoryMemberRow,
    StoryRow,
)
from app.disagreement.rollup import aggregate_pairs
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

        counters["pair_months"] = _rebuild_pair_rollup(session, now=now)
        session.commit()

    return counters


def _rebuild_pair_rollup(session: Session, *, now: datetime) -> int:
    """Rebuild the (country-pair, month) roll-up from all persisted story rows.

    Overwrite-in-place per (pair, month, method version); pairs that vanish
    from the source rows (method change, deleted stories) are removed so the
    table always mirrors exactly what the story rows support.
    """
    rows = session.execute(
        select(StoryDisagreementRow.components, StoryRow.first_seen)
        .join(StoryRow, StoryRow.id == StoryDisagreementRow.story_id)
        .where(StoryDisagreementRow.method_version == METHOD_VERSION)
    ).all()
    aggregated = aggregate_pairs(
        [{"components": components, "first_seen": first_seen} for components, first_seen in rows]
    )

    existing = {
        (row.country_a, row.country_b, row.month.isoformat()): row
        for row in session.execute(
            select(DisagreementPairRow).where(DisagreementPairRow.method_version == METHOD_VERSION)
        ).scalars()
    }
    for key, stats in aggregated.items():
        row = existing.pop(key, None)
        if row is None:
            country_a, country_b, month = key
            session.add(
                DisagreementPairRow(
                    country_a=country_a,
                    country_b=country_b,
                    month=date_type.fromisoformat(month),
                    n_stories=stats["n_stories"],
                    mean_divergence=stats["mean_divergence"],
                    method_version=METHOD_VERSION,
                    computed_at=now,
                )
            )
        else:
            row.n_stories = stats["n_stories"]
            row.mean_divergence = stats["mean_divergence"]
            row.computed_at = now
    for orphan in existing.values():
        session.delete(orphan)

    return len(aggregated)
