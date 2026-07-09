"""Round-trip tests for `app.corroboration.task` persistence via SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.corroboration import task as corro_task
from app.db_models import EventRow, StorySensorCheckRow
from app.stories import task as stories_task

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def _news(
    event_id: int, title: str, source: str, country: str | None, minutes: int = 0
) -> EventRow:
    return EventRow(
        id=event_id,
        source=source,
        source_event_id=f"e{event_id}",
        occurred_at=NOW + timedelta(minutes=minutes),
        category="news",
        keywords=[],
        country=country,
        payload={"title": title},
    )


def _quake(event_id: int, country: str | None, hours_before: float, place: str = "") -> EventRow:
    return EventRow(
        id=event_id,
        source="usgs-quake",
        source_event_id=f"q{event_id}",
        occurred_at=NOW - timedelta(hours=hours_before),
        category="hazard",
        keywords=[],
        country=country,
        severity=0.3,
        payload={"place": place},
    )


def _run_both(db_session: Session) -> dict:
    engine = db_session.get_bind()
    with (
        patch.object(stories_task, "get_engine", return_value=engine),
        patch.object(corro_task, "get_engine", return_value=engine),
    ):
        stories_task._cluster_stories_body(now=NOW)
        return corro_task._sensor_checks_body(now=NOW)


def _rerun(db_session: Session) -> dict:
    engine = db_session.get_bind()
    with patch.object(corro_task, "get_engine", return_value=engine):
        return corro_task._sensor_checks_body(now=NOW)


def test_earthquake_story_confirmed_by_usgs_row(db_session: Session) -> None:
    db_session.add_all(
        [
            _news(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-a", "JP"),
            _news(2, "Dozens injured as powerful earthquake hits Tokyo", "rss-b", "JP", 5),
            _quake(50, None, hours_before=4, place="12 km N of Sendai, Japan"),
        ]
    )
    db_session.commit()

    counters = _run_both(db_session)
    assert counters["confirmed"] == 1

    (check,) = db_session.execute(select(StorySensorCheckRow)).scalars().all()
    assert check.claim_type == "earthquake"
    assert check.verdict == "confirmed"
    assert check.matched_event_id == 50
    assert check.method_version == "sensor-rules-v1.0"


def test_no_claim_stories_store_nothing(db_session: Session) -> None:
    db_session.add(_news(1, "Central bank raises interest rates", "rss-a", "US"))
    db_session.commit()

    counters = _run_both(db_session)
    assert counters["claims"] == 0
    assert db_session.execute(select(StorySensorCheckRow)).scalars().all() == []


def test_unconfirmed_when_no_sensor_row(db_session: Session) -> None:
    db_session.add(_news(1, "Massive earthquake devastates Santiago region", "rss-a", "CL"))
    db_session.commit()

    _run_both(db_session)
    (check,) = db_session.execute(select(StorySensorCheckRow)).scalars().all()
    assert check.verdict == "unconfirmed"
    assert check.matched_event_id is None


def test_rerun_upserts_and_never_downgrades_confirmed(db_session: Session) -> None:
    db_session.add_all(
        [
            _news(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-a", "JP"),
            _quake(50, "JP", hours_before=4),
        ]
    )
    db_session.commit()
    _run_both(db_session)

    # Retention deletes the sensor row; the confirmed verdict must survive.
    db_session.delete(db_session.get(EventRow, 50))
    db_session.commit()
    counters = _rerun(db_session)

    checks = db_session.execute(select(StorySensorCheckRow)).scalars().all()
    assert len(checks) == 1
    assert checks[0].verdict == "confirmed"
    assert counters["kept_confirmed"] == 1


def test_scores_persisted_for_window_stories(db_session: Session) -> None:
    """WS-C step 4 (#363): every story in the window gets a corroboration row."""
    from app.db_models import StoryCorroborationRow

    db_session.add_all(
        [
            _news(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-bbc-world", "JP"),
            _news(2, "Dozens injured as powerful earthquake hits Tokyo", "rss-dawn", "JP", 5),
            _quake(50, "JP", hours_before=4),
        ]
    )
    db_session.commit()
    counters = _run_both(db_session)
    assert counters["scored"] == 1

    (row,) = db_session.execute(select(StoryCorroborationRow)).scalars().all()
    assert row.method_version == "corroboration-v1.0"
    # 2 independent owners (bbc, dawn-media) + a confirmed quake → 1 - 2^-2.
    assert row.score == 0.75
    assert row.components["owner_count"] == 2
    assert row.components["confirmed_claims"] == 1

    # Re-run overwrites in place, never duplicates.
    _rerun(db_session)
    rows = db_session.execute(select(StoryCorroborationRow)).scalars().all()
    assert len(rows) == 1


def test_claimless_story_scored_on_owners_alone(db_session: Session) -> None:
    from app.db_models import StoryCorroborationRow

    db_session.add(_news(1, "Central bank raises interest rates", "rss-a", "US"))
    db_session.commit()
    _run_both(db_session)

    (row,) = db_session.execute(select(StoryCorroborationRow)).scalars().all()
    assert row.score == 0.0
    assert row.components["claims_checked"] == 0


def test_beat_schedule_has_sensor_checks_entry() -> None:
    from app.tasks import app as celery_app

    entry = celery_app.conf.beat_schedule["sensor-checks-30min"]
    assert entry["task"] == "app.tasks.sensor_check_stories"
