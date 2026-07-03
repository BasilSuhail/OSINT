"""Tests for `app.journal.emit` — composite scores → immutable predictions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import PredictionRow
from app.journal.emit import predictions_from_scores, upsert_predictions

JAN = datetime(2026, 1, 1, tzinfo=UTC)
ISSUANCE = datetime(2026, 1, 15, tzinfo=UTC)  # same month as the bucket → forward forecast


def _score(value: float = 0.7) -> dict:
    return {
        "country": "SY",
        "bucket_start": JAN,
        "score_value": value,
        "components": {"z": {"geopolitical": 2.0}},
        "method_version": "v1.0",
    }


class TestPredictionsFromScores:
    def test_one_score_yields_three_horizons(self) -> None:
        preds = predictions_from_scores([_score()], now=ISSUANCE)
        assert sorted(p["horizon_months"] for p in preds) == [1, 3, 6]
        assert all(p["score"] == 0.7 for p in preds)
        assert all(p["source"] == "composite" for p in preds)
        assert all(p["country"] == "SY" for p in preds)

    def test_payload_snapshots_components(self) -> None:
        (pred, *_) = predictions_from_scores([_score()], now=ISSUANCE)
        assert pred["payload"]["components"] == {"z": {"geopolitical": 2.0}}


class TestUpsertPredictions:
    def test_insert_returns_issued_count(self, db_session: Session) -> None:
        preds = predictions_from_scores([_score()], now=ISSUANCE)
        assert upsert_predictions(preds, db_session) == 3

    def test_reissue_is_noop(self, db_session: Session) -> None:
        preds = predictions_from_scores([_score()], now=ISSUANCE)
        upsert_predictions(preds, db_session)
        assert upsert_predictions(preds, db_session) == 0

    def test_issued_prediction_survives_score_revision(self, db_session: Session) -> None:
        upsert_predictions(predictions_from_scores([_score(0.7)], now=ISSUANCE), db_session)
        # composite reruns with revised data → score changed
        upsert_predictions(predictions_from_scores([_score(0.2)], now=ISSUANCE), db_session)
        rows = db_session.execute(select(PredictionRow)).scalars().all()
        assert len(rows) == 3
        assert all(row.score == 0.7 for row in rows)

    def test_issued_at_stamped(self, db_session: Session) -> None:
        upsert_predictions(predictions_from_scores([_score()], now=ISSUANCE), db_session)
        (row, *_) = db_session.execute(select(PredictionRow)).scalars().all()
        assert row.issued_at is not None
        assert row.outcome is None


class TestHindcastGuard:
    def test_past_month_bucket_is_skipped(self) -> None:
        later = datetime(2026, 7, 3, tzinfo=UTC)
        assert predictions_from_scores([_score()], now=later) == []

    def test_current_month_bucket_is_issued(self) -> None:
        same_month = datetime(2026, 1, 31, 23, 59, tzinfo=UTC)
        assert len(predictions_from_scores([_score()], now=same_month)) == 3
