"""Tests for `app.journal.scoreboard` — track-record stats."""

from __future__ import annotations

import pytest

from app.journal.scoreboard import build_scoreboard


def _row(*, horizon: int = 1, score: float = 0.8, outcome: int | None = None) -> dict:
    return {
        "source": "composite",
        "method_version": "v1.0",
        "horizon_months": horizon,
        "score": score,
        "outcome": outcome,
    }


def test_pending_and_graded_split() -> None:
    rows = [_row(outcome=1), _row(outcome=0), _row()]
    (line,) = build_scoreboard(rows)
    assert line["issued"] == 3
    assert line["graded"] == 2
    assert line["pending"] == 1


def test_hit_rate_and_brier_hand_computed() -> None:
    rows = [
        _row(score=0.8, outcome=1),  # brier (0.8-1)^2 = 0.04
        _row(score=0.6, outcome=0),  # brier 0.36
    ]
    (line,) = build_scoreboard(rows)
    assert line["positive_rate"] == 0.5
    assert line["brier"] == pytest.approx(0.2)
    assert line["mean_score"] == pytest.approx(0.7)


def test_grouped_by_source_and_horizon() -> None:
    rows = [_row(horizon=1), _row(horizon=3), _row(horizon=3)]
    lines = build_scoreboard(rows)
    assert [(line["horizon_months"], line["issued"]) for line in lines] == [(1, 1), (3, 2)]


def test_no_graded_rows_yields_none_metrics() -> None:
    (line,) = build_scoreboard([_row()])
    assert line["brier"] is None
    assert line["positive_rate"] is None


def test_beat_schedule_has_journal_entry() -> None:
    from app.tasks import app as celery_app

    entry = celery_app.conf.beat_schedule["journal-daily-2am-utc"]
    assert entry["task"] == "app.tasks.journal_daily"
