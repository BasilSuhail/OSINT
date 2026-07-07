"""Tests for `app.composite.persistence` — batched score upserts (#336)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.composite import persistence
from app.composite.persistence import upsert_scores
from app.composite.scoring import ComposedScore
from app.db_models import ScoreRow


def _score(month: int, value: float = 0.5) -> ComposedScore:
    return ComposedScore(
        country="SY",
        bucket_start=datetime(2015, month, 1, tzinfo=UTC),
        bucket_length=timedelta(days=30),
        score_name="composite",
        score_value=value,
        components={"backfill": True},
        method_version="v1.0",
    )


class TestUpsertScoresBatching:
    def test_upsert_spanning_multiple_batches(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(persistence, "BATCH_SIZE", 4)
        scores = [_score(month) for month in range(1, 13)]  # 12 rows, 3 batches
        touched = upsert_scores(scores, db_session)
        db_session.commit()
        assert touched == 12
        assert len(db_session.execute(select(ScoreRow)).scalars().all()) == 12

    def test_rerun_refreshes_across_batches(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(persistence, "BATCH_SIZE", 4)
        upsert_scores([_score(m, 0.2) for m in range(1, 13)], db_session)
        db_session.commit()
        upsert_scores([_score(m, 0.9) for m in range(1, 13)], db_session)
        db_session.commit()
        rows = db_session.execute(select(ScoreRow)).scalars().all()
        assert len(rows) == 12
        assert all(row.score_value == 0.9 for row in rows)

    def test_empty_input_touches_nothing(self, db_session: Session) -> None:
        assert upsert_scores([], db_session) == 0
