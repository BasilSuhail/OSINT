"""Tests for the weekly briefing export — the newsletter artifact (#401)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.briefing.render import render_markdown
from app.db_models import (
    PredictionRow,
    ScoreRow,
    StoryCorroborationRow,
    StoryDisagreementRow,
    StoryRow,
)

NOW = datetime(2026, 7, 13, 6, 30, tzinfo=UTC)  # a Monday


def _fixture_briefing() -> dict:
    return {
        "week_start": "2026-07-06",
        "week_end": "2026-07-13",
        "stress": {"word": "elevated", "mean": 0.61, "month": "2026-07"},
        "movers": [
            {"country": "VE", "latest": 0.82, "delta": 0.31},
            {"country": "NZ", "latest": 0.22, "delta": -0.18},
        ],
        "top_stories": [
            {
                "title": "Powerful earthquake strikes Tokyo",
                "owner_count": 5,
                "corroboration": 0.9375,
                "confirmed": ["earthquake"],
            }
        ],
        "contested": [
            {
                "title": "Ceasefire no longer in effect",
                "divergence": 0.885,
                "groups": {"GB": 4, "RU": 4},
            }
        ],
        "scoreboard": [
            {
                "source": "composite",
                "horizon_months": 1,
                "issued": 155,
                "graded": 0,
                "pending": 155,
                "brier": None,
            }
        ],
    }


def test_render_markdown_carries_every_section() -> None:
    md = render_markdown(_fixture_briefing())
    assert "# OSINT Weekly Briefing" in md
    assert "2026-07-06" in md and "2026-07-13" in md
    assert "ELEVATED" in md  # stress word, loud
    assert "Venezuela" in md and "▲" in md  # mover, full name, direction
    assert "Powerful earthquake strikes Tokyo" in md
    assert "5 independent owners" in md
    assert "sensor-confirmed: earthquake" in md
    assert "United Kingdom" in md and "Russia" in md  # contested groups, full names
    assert "0.885" in md
    assert "coin flip" in md  # honesty footer explains Brier anchors
    assert "on trial" in md  # track-record honesty line


def test_render_markdown_handles_empty_week() -> None:
    briefing = _fixture_briefing() | {
        "top_stories": [],
        "contested": [],
        "movers": [],
        "scoreboard": [],
    }
    md = render_markdown(briefing)
    assert "no multi-source stories" in md
    assert "no cross-country tellings" in md


def _seed(db_session: Session) -> None:
    story = StoryRow(
        method_version="stories-v1.0",
        title="Powerful earthquake strikes Tokyo",
        first_seen=NOW - timedelta(days=2),
        last_seen=NOW - timedelta(days=1),
        member_count=3,
        outlet_count=3,
        owner_count=3,
    )
    db_session.add(story)
    db_session.flush()
    db_session.add_all(
        [
            StoryCorroborationRow(
                story_id=story.id,
                score=0.75,
                components={"owner_count": 3},
                method_version="corroboration-v1.0",
                computed_at=NOW - timedelta(days=1),
            ),
            StoryDisagreementRow(
                story_id=story.id,
                divergence=0.6,
                components={"groups": {"GB": 1, "JP": 2}, "n_pairs": 1},
                method_version="disagreement-v1.0",
                computed_at=NOW - timedelta(days=1),
            ),
            PredictionRow(
                source="composite",
                method_version="v1.0",
                country="JP",
                bucket_start=datetime(2026, 7, 1, tzinfo=UTC),
                horizon_months=1,
                score=0.4,
                payload={},
            ),
        ]
    )
    for month, value in [(6, 0.3), (7, 0.6)]:
        db_session.add(
            ScoreRow(
                country="JP",
                bucket_start=datetime(2026, month, 1, tzinfo=UTC),
                bucket_length=timedelta(days=31),
                score_name="composite",
                score_value=value,
                components={},
                method_version="v1.0",
            )
        )
    db_session.commit()


def test_task_round_trip_writes_exports(db_session: Session, tmp_path, monkeypatch) -> None:
    from app.briefing import task as briefing_task

    monkeypatch.setenv("OSINT_DATA_DIR", str(tmp_path))
    _seed(db_session)
    engine = db_session.get_bind()
    with patch.object(briefing_task, "get_engine", return_value=engine):
        counters = briefing_task._briefing_body(now=NOW)

    assert counters["top_stories"] == 1
    assert counters["contested"] == 1
    md = (tmp_path / "exports" / "weekly-briefing.md").read_text()
    assert "Powerful earthquake strikes Tokyo" in md
    assert (tmp_path / "exports" / "weekly-briefing.json").exists()


def test_beat_schedule_has_weekly_briefing() -> None:
    from app.tasks import app as celery_app

    entry = celery_app.conf.beat_schedule["briefing-weekly"]
    assert entry["task"] == "app.tasks.weekly_briefing"
    assert celery_app.conf.task_routes["app.tasks.weekly_briefing"]["queue"] == "analytics"
