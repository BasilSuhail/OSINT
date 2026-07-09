"""Tests for the WS-B forward exam — divergence exposures into the journal (#374)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import DisagreementPairRow, EventRow, PredictionRow
from app.disagreement import task as disagreement_task
from app.disagreement.exam import divergence_exposures
from app.journal import task as journal_task
from app.stories import task as stories_task

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def _pair(a: str, b: str, month: str, n: int, mean: float) -> dict:
    return {
        "country_a": a,
        "country_b": b,
        "month": date.fromisoformat(month),
        "n_stories": n,
        "mean_divergence": mean,
    }


def test_exposure_is_story_weighted_mean_over_containing_pairs() -> None:
    exposures = divergence_exposures(
        [
            _pair("GB", "RU", "2026-07-01", n=3, mean=0.9),
            _pair("RU", "US", "2026-07-01", n=1, mean=0.5),
            _pair("GB", "US", "2026-06-01", n=2, mean=0.2),
        ]
    )
    by_key = {(e["country"], e["bucket_start"].date().isoformat()): e for e in exposures}
    ru = by_key[("RU", "2026-07-01")]
    assert abs(ru["score_value"] - (3 * 0.9 + 1 * 0.5) / 4) < 1e-9
    assert ru["components"] == {"n_pairs": 2, "n_stories": 4}
    assert ru["method_version"] == "disagreement-v1.0"
    assert by_key[("GB", "2026-06-01")]["score_value"] == 0.2
    assert by_key[("US", "2026-07-01")]["score_value"] == 0.5


def test_exposures_empty_for_no_rows() -> None:
    assert divergence_exposures([]) == []


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


def test_journal_issues_disagreement_predictions(db_session: Session) -> None:
    """End-to-end: cluster → divergence → roll-up → journal emits source=disagreement."""
    db_session.add_all(
        [
            _news(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-bbc-world"),
            _news(2, "Dozens injured as powerful earthquake hits Tokyo", "rss-tass-en", 5),
        ]
    )
    db_session.commit()
    engine = db_session.get_bind()
    with (
        patch.object(stories_task, "get_engine", return_value=engine),
        patch.object(disagreement_task, "get_engine", return_value=engine),
    ):
        stories_task._cluster_stories_body(now=NOW)
        disagreement_task._disagreement_body(now=NOW)

    with patch.object(journal_task, "get_engine", return_value=engine):
        counters = journal_task._journal_daily_inner()

    rows = (
        db_session.execute(select(PredictionRow).where(PredictionRow.source == "disagreement"))
        .scalars()
        .all()
    )
    # GB and RU exposures x horizons 1/3/6.
    assert len(rows) == 6
    assert {r.country for r in rows} == {"GB", "RU"}
    assert {r.horizon_months for r in rows} == {1, 3, 6}
    assert all(r.method_version == "disagreement-v1.0" for r in rows)
    assert all(0.0 <= r.score <= 1.0 for r in rows)
    assert counters["issued_disagreement"] == 6


def test_hindcast_guard_applies_to_disagreement(db_session: Session) -> None:
    """A past-month pair row must not fake a forward prediction."""
    db_session.add(
        DisagreementPairRow(
            country_a="GB",
            country_b="RU",
            month=date(2026, 5, 1),
            n_stories=4,
            mean_divergence=0.8,
            method_version="disagreement-v1.0",
        )
    )
    db_session.commit()

    engine = db_session.get_bind()
    with patch.object(journal_task, "get_engine", return_value=engine):
        journal_task._journal_daily_inner()

    rows = (
        db_session.execute(select(PredictionRow).where(PredictionRow.source == "disagreement"))
        .scalars()
        .all()
    )
    assert rows == []
