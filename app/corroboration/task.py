"""Corroboration worker body — sensor verdicts + score per story in the window.

For every story still inside the clustering window: detect physical claims in
its member titles, check each claim against its sensor source (rules in
`app.corroboration.rules`), then fold owner_count and the story's verdicts
into the fixed corroboration-v1.0 score (`app.corroboration.score`). Called
by the 30-minute beat task in `app.tasks` and by `make sensor-checks`. Runs
right after clustering beats so fresh stories are checked while their sensor
evidence (hazard retention ~2 days) still exists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.corroboration.rules import (
    CLAIM_SENSOR_SOURCE,
    LOOKAHEAD_HOURS,
    LOOKBACK_HOURS,
    METHOD_VERSION,
    detect_claims,
    evaluate_claim,
)
from app.corroboration.score import SCORE_VERSION, corroboration_score
from app.db import get_engine
from app.db_models import (
    EventRow,
    StoryCorroborationRow,
    StoryMemberRow,
    StoryRow,
    StorySensorCheckRow,
)
from app.stories.task import WINDOW_HOURS


def _sensor_checks_body(*, now: datetime | None = None) -> dict[str, Any]:
    from app.jobs.heartbeat import job_run

    factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    with job_run("sensor-checks", session_factory=factory):
        return _sensor_checks_inner(now=now)


def _sensor_checks_inner(*, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=WINDOW_HOURS)
    counters = {
        "stories": 0,
        "claims": 0,
        "confirmed": 0,
        "unconfirmed": 0,
        "kept_confirmed": 0,
        "scored": 0,
    }

    with Session(get_engine()) as session:
        stories = (
            session.execute(select(StoryRow).where(StoryRow.last_seen >= cutoff)).scalars().all()
        )
        for story in stories:
            member_rows = session.execute(
                select(EventRow.payload, EventRow.country)
                .join(StoryMemberRow, StoryMemberRow.event_id == EventRow.id)
                .where(StoryMemberRow.story_id == story.id)
            ).all()
            titles = [(payload or {}).get("title") or "" for payload, _ in member_rows]
            claims = detect_claims(titles)
            if not claims:
                _upsert_score(session, story, now=now)
                counters["scored"] += 1
                continue
            counters["stories"] += 1

            story_countries = {country for _, country in member_rows if country}
            window = (
                story.first_seen - timedelta(hours=LOOKBACK_HOURS),
                story.last_seen + timedelta(hours=LOOKAHEAD_HOURS),
            )

            for claim in sorted(claims):
                counters["claims"] += 1
                existing = session.execute(
                    select(StorySensorCheckRow).where(
                        StorySensorCheckRow.story_id == story.id,
                        StorySensorCheckRow.claim_type == claim,
                        StorySensorCheckRow.method_version == METHOD_VERSION,
                    )
                ).scalar_one_or_none()
                if existing is not None and existing.verdict == "confirmed":
                    counters["kept_confirmed"] += 1
                    continue

                sensor_rows = session.execute(
                    select(
                        EventRow.id,
                        EventRow.source,
                        EventRow.occurred_at,
                        EventRow.country,
                        EventRow.severity,
                        EventRow.payload,
                    ).where(
                        EventRow.source == CLAIM_SENSOR_SOURCE[claim],
                        EventRow.occurred_at >= window[0],
                        EventRow.occurred_at <= window[1],
                    )
                ).all()
                check = evaluate_claim(
                    claim,
                    story_countries=story_countries,
                    window=window,
                    sensors=[
                        {
                            "event_id": row.id,
                            "source": row.source,
                            "occurred_at": row.occurred_at,
                            "country": row.country,
                            "severity": row.severity,
                            "payload": row.payload,
                        }
                        for row in sensor_rows
                    ],
                )
                counters[check["verdict"]] += 1

                if existing is None:
                    session.add(
                        StorySensorCheckRow(
                            story_id=story.id,
                            claim_type=claim,
                            verdict=check["verdict"],
                            matched_event_id=check["matched_event_id"],
                            evidence=check["evidence"],
                            method_version=METHOD_VERSION,
                            checked_at=now,
                        )
                    )
                else:
                    existing.verdict = check["verdict"]
                    existing.matched_event_id = check["matched_event_id"]
                    existing.evidence = check["evidence"]
                    existing.checked_at = now

            session.flush()
            _upsert_score(session, story, now=now)
            counters["scored"] += 1

        session.commit()

    return counters


def _upsert_score(session: Session, story: StoryRow, *, now: datetime) -> None:
    """Fold the story's owners and persisted verdicts into corroboration-v1.0."""
    verdicts = session.execute(
        select(StorySensorCheckRow.verdict).where(StorySensorCheckRow.story_id == story.id)
    ).scalars()
    tally = {"confirmed": 0, "unconfirmed": 0}
    for verdict in verdicts:
        tally[verdict] = tally.get(verdict, 0) + 1

    score, components = corroboration_score(
        owner_count=story.owner_count,
        confirmed=tally["confirmed"],
        unconfirmed=tally["unconfirmed"],
    )
    existing = session.execute(
        select(StoryCorroborationRow).where(
            StoryCorroborationRow.story_id == story.id,
            StoryCorroborationRow.method_version == SCORE_VERSION,
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            StoryCorroborationRow(
                story_id=story.id,
                score=score,
                components=components,
                method_version=SCORE_VERSION,
                computed_at=now,
            )
        )
    else:
        existing.score = score
        existing.components = components
        existing.computed_at = now
