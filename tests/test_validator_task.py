"""Round-trip tests for `app.validator.task` — batch extraction, no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow, StoryClaimRow
from app.stories import task as stories_task
from app.validator import task as validator_task
from app.validator.claims import OLLAMA_MODEL_DEFAULT

NOW = datetime(2026, 7, 10, 2, 45, tzinfo=UTC)


def _news(event_id: int, title: str, source: str, minutes: int = 0) -> EventRow:
    return EventRow(
        id=event_id,
        source=source,
        source_event_id=f"e{event_id}",
        occurred_at=NOW - timedelta(hours=1) + timedelta(minutes=minutes),
        category="news",
        keywords=[],
        payload={"title": title},
    )


def _run(db_session: Session, fake_response: dict) -> dict:
    engine = db_session.get_bind()
    with (
        patch.object(stories_task, "get_engine", return_value=engine),
        patch.object(validator_task, "get_engine", return_value=engine),
        patch.object(validator_task, "generate_json", return_value=fake_response) as gen,
    ):
        stories_task._cluster_stories_body(now=NOW)
        counters = validator_task._validator_body(now=NOW)
    return {"counters": counters, "calls": gen.call_args_list}


def test_batch_extracts_and_persists_claims(db_session: Session) -> None:
    db_session.add_all(
        [
            _news(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-a"),
            _news(2, "Dozens injured as powerful earthquake hits Tokyo", "rss-b", 5),
        ]
    )
    db_session.commit()

    out = _run(
        db_session,
        {"countries": ["JP"], "event_type": "earthquake", "casualties": 12},
    )
    assert out["counters"]["extracted"] == 1

    (row,) = db_session.execute(select(StoryClaimRow)).scalars().all()
    assert row.claims == {"countries": ["JP"], "event_type": "earthquake", "casualties": 12}
    assert row.model == OLLAMA_MODEL_DEFAULT
    assert row.prompt_version
    # The prompt actually carried the member titles.
    prompt = out["calls"][0].args[0]
    assert "earthquake" in prompt.lower()


def test_rerun_skips_already_extracted(db_session: Session) -> None:
    db_session.add(_news(1, "Powerful earthquake strikes eastern Turkey", "rss-a"))
    db_session.commit()
    _run(db_session, {"countries": ["TR"], "event_type": "earthquake", "casualties": None})
    out = _run(db_session, {"countries": ["TR"], "event_type": "earthquake", "casualties": None})
    assert out["counters"]["extracted"] == 0
    assert len(db_session.execute(select(StoryClaimRow)).scalars().all()) == 1


def test_batch_cap_respected(db_session: Session) -> None:
    titles = [
        "Central bank raises interest rates again",
        "Wildfire forces evacuations in southern France",
        "Parliament passes controversial media law",
    ]
    for i, title in enumerate(titles):
        db_session.add(_news(i + 1, title, f"rss-{i}", minutes=i))
    db_session.commit()

    engine = db_session.get_bind()
    with (
        patch.object(stories_task, "get_engine", return_value=engine),
        patch.object(validator_task, "get_engine", return_value=engine),
        patch.object(
            validator_task,
            "generate_json",
            return_value={"countries": [], "event_type": "none", "casualties": None},
        ),
    ):
        stories_task._cluster_stories_body(now=NOW)
        counters = validator_task._validator_body(now=NOW, batch_limit=2)
    assert counters["extracted"] == 2


def test_beat_schedule_has_validator_entry() -> None:
    from app.tasks import app as celery_app

    entry = celery_app.conf.beat_schedule["validator-nightly"]
    assert entry["task"] == "app.tasks.extract_claims"
