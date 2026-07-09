"""Round-trip tests for `app.disagreement.task` persistence via SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow, StoryDisagreementRow
from app.disagreement import task as disagreement_task
from app.stories import task as stories_task

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def _news(event_id: int, title: str, source: str, minutes: int = 0) -> EventRow:
    return EventRow(
        id=event_id,
        source=source,
        source_event_id=f"e{event_id}",
        occurred_at=NOW + timedelta(minutes=minutes),
        category="news",
        keywords=[],
        payload={"title": title},
    )


def _run_both(db_session: Session) -> dict:
    engine = db_session.get_bind()
    with (
        patch.object(stories_task, "get_engine", return_value=engine),
        patch.object(disagreement_task, "get_engine", return_value=engine),
    ):
        stories_task._cluster_stories_body(now=NOW)
        return disagreement_task._disagreement_body(now=NOW)


def test_cross_country_story_gets_divergence_row(db_session: Session) -> None:
    db_session.add_all(
        [
            # bbc-world origin GB, tass RU — same story, different wording.
            _news(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-bbc-world"),
            _news(2, "Dozens injured as powerful earthquake hits Tokyo", "rss-tass-en", 5),
        ]
    )
    db_session.commit()

    counters = _run_both(db_session)
    assert counters["scored"] == 1

    (row,) = db_session.execute(select(StoryDisagreementRow)).scalars().all()
    assert row.method_version == "disagreement-v1.0"
    assert 0.0 <= row.divergence <= 1.0
    assert set(row.components["groups"]) == {"GB", "RU"}


def test_single_country_story_skipped(db_session: Session) -> None:
    db_session.add_all(
        [
            _news(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-bbc-world"),
            _news(2, "Dozens injured as powerful earthquake hits Tokyo", "rss-bbc-uk", 5),
        ]
    )
    db_session.commit()

    counters = _run_both(db_session)
    assert counters["scored"] == 0
    assert counters["single_group"] == 1
    assert db_session.execute(select(StoryDisagreementRow)).scalars().all() == []


def test_rerun_overwrites_never_duplicates(db_session: Session) -> None:
    db_session.add_all(
        [
            _news(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-bbc-world"),
            _news(2, "Dozens injured as powerful earthquake hits Tokyo", "rss-tass-en", 5),
        ]
    )
    db_session.commit()
    _run_both(db_session)

    engine = db_session.get_bind()
    with patch.object(disagreement_task, "get_engine", return_value=engine):
        disagreement_task._disagreement_body(now=NOW)

    rows = db_session.execute(select(StoryDisagreementRow)).scalars().all()
    assert len(rows) == 1


def test_beat_schedule_has_disagreement_entry() -> None:
    from app.tasks import app as celery_app

    entry = celery_app.conf.beat_schedule["disagreement-30min"]
    assert entry["task"] == "app.tasks.score_disagreement"
