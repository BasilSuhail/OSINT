"""Tests for `app.journal.grade` — mature-window grading, exactly once."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import PredictionRow
from app.journal.emit import predictions_from_scores, upsert_predictions
from app.journal.grade import grade_pending, resolve_outcome

JAN = datetime(2026, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 7, 3, tzinfo=UTC)

COVERAGE = {"SY": (datetime(2015, 1, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC))}


def _prediction(horizon: int, bucket: datetime = JAN) -> dict:
    return {
        "country": "SY",
        "bucket_start": bucket,
        "horizon_months": horizon,
    }


class TestResolveOutcome:
    def test_positive_in_window(self) -> None:
        labels = {("SY", datetime(2026, 2, 1, tzinfo=UTC))}
        assert resolve_outcome(_prediction(1), labels, COVERAGE, now=NOW) == 1

    def test_negative_window_inside_coverage(self) -> None:
        assert resolve_outcome(_prediction(1), set(), COVERAGE, now=NOW) == 0

    def test_window_not_yet_past_is_pending(self) -> None:
        pred = _prediction(6, bucket=datetime(2026, 5, 1, tzinfo=UTC))  # window → Nov 2026
        assert resolve_outcome(pred, set(), COVERAGE, now=NOW) is None

    def test_window_outside_coverage_is_pending(self) -> None:
        pred = _prediction(1, bucket=datetime(2026, 6, 1, tzinfo=UTC))  # July outside coverage
        assert resolve_outcome(pred, set(), COVERAGE, now=NOW) is None

    def test_unknown_country_is_pending(self) -> None:
        pred = {**_prediction(1), "country": "ZZ"}
        assert resolve_outcome(pred, set(), COVERAGE, now=NOW) is None

    def test_positive_at_window_edge_counts(self) -> None:
        labels = {("SY", datetime(2026, 4, 1, tzinfo=UTC))}  # t+3 for Jan
        assert resolve_outcome(_prediction(3), labels, COVERAGE, now=NOW) == 1
        assert resolve_outcome(_prediction(2), labels, COVERAGE, now=NOW) == 0


class TestGradePending:
    def test_grades_once_and_only_once(self, db_session: Session) -> None:
        upsert_predictions(
            predictions_from_scores(
                [
                    {
                        "country": "SY",
                        "bucket_start": JAN,
                        "score_value": 0.7,
                        "components": {},
                        "method_version": "v1.0",
                    }
                ]
            ),
            db_session,
        )
        labels = {("SY", datetime(2026, 2, 1, tzinfo=UTC))}
        graded_first = grade_pending(db_session, labels, COVERAGE, now=NOW)
        assert graded_first > 0
        stamps = {
            row.id: row.graded_at
            for row in db_session.execute(select(PredictionRow)).scalars()
            if row.graded_at is not None
        }
        assert grade_pending(db_session, labels, COVERAGE, now=NOW) == 0
        for row in db_session.execute(select(PredictionRow)).scalars():
            if row.id in stamps:
                assert row.graded_at == stamps[row.id]

    def test_outcomes_written(self, db_session: Session) -> None:
        upsert_predictions(
            predictions_from_scores(
                [
                    {
                        "country": "SY",
                        "bucket_start": JAN,
                        "score_value": 0.7,
                        "components": {},
                        "method_version": "v1.0",
                    }
                ]
            ),
            db_session,
        )
        labels = {("SY", datetime(2026, 2, 1, tzinfo=UTC))}
        grade_pending(db_session, labels, COVERAGE, now=NOW)
        by_horizon = {
            row.horizon_months: row.outcome
            for row in db_session.execute(select(PredictionRow)).scalars()
        }
        assert by_horizon[1] == 1  # Feb positive inside [Feb]
        assert by_horizon[3] == 1  # inside [Feb, Apr]
        assert by_horizon[6] is None  # window Feb-Jul; July not past at NOW → pending
