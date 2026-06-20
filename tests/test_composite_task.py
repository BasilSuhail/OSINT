"""Integration test for `app.composite.task._compute_composite_body`.

Uses the global SQLite fixture from the existing task tests: insert events,
run the body, assert that scores land in the scores table.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from app import db
from app.composite import task as composite_task
from app.db_models import Base, EventRow, ScoreRow


@pytest.fixture
def global_sqlite_db() -> Iterator[Engine]:
    engine = db.reset_engine_for_testing("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    db._engine = None
    db._session_factory = None


def _session_for(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False, future=True)()


def _insert_event(
    session,
    *,
    source: str,
    source_event_id: str,
    country: str,
    category: str,
    severity: float,
    occurred_at: datetime,
) -> None:
    session.add(
        EventRow(
            source=source,
            source_event_id=source_event_id,
            occurred_at=occurred_at,
            fetched_at=datetime.now(UTC),
            category=category,
            severity=severity,
            country=country,
            keywords=[],
            payload={},
        )
    )


class TestComputeCompositeBody:
    def test_empty_events_table_returns_zero_scores(self, global_sqlite_db: Engine) -> None:
        result = composite_task._compute_composite_body()
        assert result["events_read"] == 0
        assert result["scores_written"] == 0

    def test_single_month_writes_one_score(self, global_sqlite_db: Engine) -> None:
        with _session_for(global_sqlite_db) as session:
            for i in range(3):
                _insert_event(
                    session,
                    source="yfinance",
                    source_event_id=f"SPY:{i}",
                    country="US",
                    category="market",
                    severity=0.4 + i * 0.05,
                    occurred_at=datetime.now(UTC),
                )
            session.commit()

        result = composite_task._compute_composite_body()
        assert result["events_read"] == 3
        assert result["scores_written"] == 1

        with _session_for(global_sqlite_db) as session:
            scores = session.execute(select(ScoreRow)).scalars().all()
            assert len(scores) == 1
            # Cold start: rolling z is 0, sigmoid(0) = 0.5
            assert 0.4 < scores[0].score_value < 0.6
            assert scores[0].country == "US"
            assert scores[0].method_version == "v1.0"
            assert scores[0].score_name == "composite"

    def test_filters_non_composite_categories(self, global_sqlite_db: Engine) -> None:
        with _session_for(global_sqlite_db) as session:
            _insert_event(
                session,
                source="opensky",
                source_event_id="X:1",
                country="US",
                category="tracking",
                severity=0.9,
                occurred_at=datetime.now(UTC),
            )
            session.commit()

        result = composite_task._compute_composite_body()
        assert result["events_read"] == 0  # filtered by category in SQL
        assert result["scores_written"] == 0

    def test_idempotent_rerun_refreshes_score(self, global_sqlite_db: Engine) -> None:
        with _session_for(global_sqlite_db) as session:
            _insert_event(
                session,
                source="yfinance",
                source_event_id="SPY:1",
                country="US",
                category="market",
                severity=0.4,
                occurred_at=datetime.now(UTC),
            )
            session.commit()

        composite_task._compute_composite_body()
        composite_task._compute_composite_body()  # rerun — should upsert in place

        with _session_for(global_sqlite_db) as session:
            scores = session.execute(select(ScoreRow)).scalars().all()
            assert len(scores) == 1  # not duplicated
