"""Tests for the nightly story review — contradictions + cluster QA (WS-G step 3, #386)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow, StoryReviewRow
from app.stories import task as stories_task
from app.validator import task as validator_task
from app.validator.review import REVIEW_METHOD_VERSION, build_review_prompt, parse_review

NOW = datetime(2026, 7, 10, 2, 45, tzinfo=UTC)


def test_build_review_prompt_lists_titles() -> None:
    prompt = build_review_prompt(["Quake hits Tokyo", "Tokyo tremor injures dozens"])
    assert "Quake hits Tokyo" in prompt
    assert "one_story" in prompt and "contradiction" in prompt


def test_parse_review_valid() -> None:
    got = parse_review(
        {"one_story": True, "contradiction": True, "kind": "facts", "note": "tolls differ"}
    )
    assert got == {
        "one_story": True,
        "contradiction": True,
        "kind": "facts",
        "note": "tolls differ",
    }


def test_parse_review_mechanical_validation() -> None:
    got = parse_review({"one_story": "yes", "contradiction": 1, "kind": "vibes", "note": 5})
    assert got == {"one_story": None, "contradiction": None, "kind": "none", "note": None}
    assert parse_review(None)["one_story"] is None


def test_parse_review_no_contradiction_forces_kind_none() -> None:
    got = parse_review({"one_story": True, "contradiction": False, "kind": "facts", "note": ""})
    assert got["kind"] == "none"


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


def test_multi_member_stories_get_reviews(db_session: Session) -> None:
    db_session.add_all(
        [
            _news(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-a"),
            _news(2, "Dozens injured as powerful earthquake hits Tokyo", "rss-b", 5),
            _news(3, "Central bank raises interest rates", "rss-c", 9),  # single member
        ]
    )
    db_session.commit()
    engine = db_session.get_bind()
    with (
        patch.object(stories_task, "get_engine", return_value=engine),
        patch.object(validator_task, "get_engine", return_value=engine),
        patch.object(
            validator_task,
            "generate_json",
            return_value={
                "countries": [],
                "event_type": "none",
                "casualties": None,
                "one_story": True,
                "contradiction": False,
                "kind": "none",
                "note": None,
            },
        ),
    ):
        stories_task._cluster_stories_body(now=NOW)
        counters = validator_task._validator_body(now=NOW)

    assert counters["reviewed"] == 1  # only the two-member quake story
    (review,) = db_session.execute(select(StoryReviewRow)).scalars().all()
    assert review.review["one_story"] is True
    assert review.method_version == REVIEW_METHOD_VERSION
