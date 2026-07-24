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
from app.composite.config import DEFAULT_METHOD_VERSION
from app.composite.history import load_signals, persist_signals
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
            assert scores[0].method_version == DEFAULT_METHOD_VERSION
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


class TestCeleryTaskDefault:
    """The Celery entry point must not carry its own version literal (#584).

    #574 bumped DEFAULT_METHOD_VERSION to v2.0 and updated the tests that had
    hard-coded v1.0, but `app.tasks.compute_composite` kept a literal default and
    passed it straight through. Every scheduled run then used v2.0 aggregation
    while stamping the result v1.0, so the `scores` table holds rows from two
    aggregation methods under one version label.
    """

    def test_task_default_tracks_the_constant(self):
        import inspect

        from app.composite.config import DEFAULT_METHOD_VERSION
        from app.tasks import compute_composite

        default = inspect.signature(compute_composite).parameters["method_version"].default

        assert default == DEFAULT_METHOD_VERSION


class TestPersistedHistory:
    """#586: retention deletes the months the z-score needs, so every live
    score was exactly 0.5. History now outlives the events."""

    def test_a_run_records_its_months_for_later(self, global_sqlite_db: Engine) -> None:
        with _session_for(global_sqlite_db) as session:
            _insert_event(
                session,
                source="gdacs",
                source_event_id="EQ:1",
                country="US",
                category="hazard",
                severity=0.4,
                occurred_at=datetime(2026, 5, 12, tzinfo=UTC),
            )
            session.commit()

        composite_task._compute_composite_body()

        with _session_for(global_sqlite_db) as session:
            stored = load_signals(session)
        assert stored == {("US", datetime(2026, 5, 1, tzinfo=UTC)): {"hazard": 0.4}}

    def test_stored_history_breaks_the_permanent_0_5(self, global_sqlite_db: Engine) -> None:
        # The exact #586 shape: months of history exist, but the events behind
        # them were pruned weeks ago. Only the newest month is still in events.
        with _session_for(global_sqlite_db) as session:
            persist_signals(
                {
                    ("US", datetime(2026, m, 1, tzinfo=UTC)): {"hazard": value}
                    for m, value in ((1, 0.10), (2, 0.15), (3, 0.12), (4, 0.14))
                },
                session,
            )
            _insert_event(
                session,
                source="gdacs",
                source_event_id="EQ:big",
                country="US",
                category="hazard",
                severity=0.95,  # a catastrophe against a quiet baseline
                occurred_at=datetime(2026, 5, 12, tzinfo=UTC),
            )
            session.commit()

        composite_task._compute_composite_body()

        with _session_for(global_sqlite_db) as session:
            latest = (
                session.execute(
                    select(ScoreRow)
                    .where(ScoreRow.bucket_start == datetime(2026, 5, 1, tzinfo=UTC))
                    .where(ScoreRow.country == "US")
                )
                .scalars()
                .one()
            )
        assert latest.score_value > 0.6, "the composite is still stuck at its neutral midpoint"
        assert latest.components["z"]["hazard"] > 0

    def test_history_is_read_even_when_the_events_table_is_empty(
        self, global_sqlite_db: Engine
    ) -> None:
        with _session_for(global_sqlite_db) as session:
            persist_signals(
                {
                    ("PK", datetime(2026, m, 1, tzinfo=UTC)): {"hazard": 0.2 * m}
                    for m in range(1, 5)
                },
                session,
            )
            session.commit()

        result = composite_task._compute_composite_body()

        assert result["events_read"] == 0
        assert result["scores_written"] == 4, "stored history alone should still score"
