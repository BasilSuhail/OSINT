"""Round-trip tests for `app.stories.task` persistence via SQLite."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow, StoryMemberRow, StoryRow
from app.stories import task as stories_task

NOW = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)


def _news(event_id: int, title: str, source: str, minutes: int = 0) -> EventRow:
    return EventRow(
        id=event_id,
        source=source,
        source_event_id=f"e{event_id}",
        occurred_at=NOW.replace(minute=minutes),
        category="news",
        keywords=[],
        payload={"title": title},
    )


def _run(db_session: Session) -> dict:
    engine = db_session.get_bind()
    with patch.object(stories_task, "get_engine", return_value=engine):
        return stories_task._cluster_stories_body(now=NOW)


def test_round_trip_clusters_and_persists(db_session: Session) -> None:
    db_session.add_all(
        [
            _news(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-a", 0),
            _news(2, "Dozens injured as powerful earthquake hits Tokyo", "rss-b", 5),
            _news(3, "Central bank raises interest rates amid inflation fears", "rss-c", 9),
        ]
    )
    db_session.commit()

    counters = _run(db_session)
    assert counters == {
        "window_news": 3,
        "newly_assigned": 3,
        "new_stories": 2,
        "joined_existing": 0,
    }
    stories = db_session.execute(select(StoryRow)).scalars().all()
    quake = next(s for s in stories if "earthquake" in s.title.lower())
    assert quake.member_count == 2
    assert quake.outlet_count == 2
    assert quake.owner_count == 2  # rss-a / rss-b unmapped → own owners


def test_rerun_is_noop(db_session: Session) -> None:
    db_session.add(_news(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-a"))
    db_session.commit()
    _run(db_session)
    counters = _run(db_session)
    assert counters["newly_assigned"] == 0
    assert counters["new_stories"] == 0


def test_new_article_joins_persisted_story(db_session: Session) -> None:
    db_session.add_all(
        [
            _news(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-a", 0),
            _news(2, "Dozens injured as powerful earthquake hits Tokyo", "rss-b", 5),
        ]
    )
    db_session.commit()
    _run(db_session)

    db_session.add(_news(3, "Tokyo earthquake: injured toll rises to dozens", "rss-c", 30))
    db_session.commit()
    counters = _run(db_session)
    assert counters["new_stories"] == 0
    assert counters["joined_existing"] == 1

    (story,) = db_session.execute(select(StoryRow)).scalars().all()
    assert story.member_count == 3
    assert story.outlet_count == 3
    members = db_session.execute(select(StoryMemberRow)).scalars().all()
    assert {m.story_id for m in members} == {story.id}


def test_owner_count_uses_real_registry_on_both_paths(db_session: Session) -> None:
    """WS-C step 2 (#355): BBC World + BBC UK are one owner on found *and* refreshed stories."""
    db_session.add_all(
        [
            _news(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-bbc-world", 0),
            _news(2, "Dozens injured as powerful earthquake hits Tokyo", "rss-bbc-uk", 5),
        ]
    )
    db_session.commit()
    _run(db_session)

    (story,) = db_session.execute(select(StoryRow)).scalars().all()
    assert story.outlet_count == 2
    assert story.owner_count == 1  # both feeds are BBC

    db_session.add(_news(3, "Tokyo earthquake: injured toll rises to dozens", "rss-dawn", 30))
    db_session.commit()
    _run(db_session)

    db_session.refresh(story)
    assert story.outlet_count == 3
    assert story.owner_count == 2  # BBC + Dawn


def test_beat_schedule_has_stories_entry() -> None:
    from app.tasks import app as celery_app

    entry = celery_app.conf.beat_schedule["stories-cluster-30min"]
    assert entry["task"] == "app.tasks.cluster_stories"


def test_title_follows_the_story_as_it_develops(db_session: Session) -> None:
    """A story's title must not stay frozen at its first report (#516).

    Story 12662 in production entered at 12:31 as "leaves at least one dead"
    and was still titled that at 18:26, while eight outlets had converged on
    five or six deaths. The title is what the situation list shows and what the
    brain cites, so the earliest and least-informed account was winning.
    """
    db_session.add(_news(1, "Earthquake in Peru leaves at least one dead", "rss-a", 0))
    db_session.commit()
    _run(db_session)

    story = db_session.execute(select(StoryRow)).scalars().one()
    assert story.title == "Earthquake in Peru leaves at least one dead"
    assert story.first_title == "Earthquake in Peru leaves at least one dead"

    # Two outlets follow with a corrected toll.
    db_session.add_all(
        [
            _news(2, "Earthquake in Peru leaves at least five dead", "rss-b", 20),
            _news(3, "At least five killed in central Peru earthquake", "rss-c", 40),
        ]
    )
    db_session.commit()
    _run(db_session)

    #: The task commits through its own Session; expire so this one re-reads.
    db_session.expire_all()
    story = db_session.execute(select(StoryRow)).scalars().one()
    assert story.member_count == 3
    # Newest member wins: the latest report supersedes the first.
    assert story.title == "At least five killed in central Peru earthquake"
    # The original survives, so the drift stays auditable and measurable.
    assert story.first_title == "Earthquake in Peru leaves at least one dead"


def test_first_title_is_never_overwritten(db_session: Session) -> None:
    db_session.add(_news(1, "Blast reported near port", "rss-a", 0))
    db_session.commit()
    _run(db_session)
    db_session.add(_news(2, "Blast near port kills three, officials say", "rss-b", 30))
    db_session.commit()
    _run(db_session)
    _run(db_session)

    db_session.expire_all()
    story = db_session.execute(select(StoryRow)).scalars().one()
    assert story.first_title == "Blast reported near port"
    assert story.title == "Blast near port kills three, officials say"
