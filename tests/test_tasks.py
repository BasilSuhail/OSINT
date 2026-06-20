"""Tests for `app.tasks._run_fetcher_body`.

The Celery layer is thin — Celery just calls the body function. Tests target
the body directly so the suite stays hermetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from app import db, fetcher_registry, tasks
from app.db_models import Base, EventRow, IngestFailureRow, IngestHealthRow
from app.models import Category, Event
from app.sources.base import Fetcher


class _StubFetcher(Fetcher):
    name = "stub"
    queue = "fast"

    def __init__(self, events: list[Event], *, raises: Exception | None = None) -> None:
        self._events = events
        self._raises = raises

    def fetch(self) -> list[Event]:
        if self._raises is not None:
            raise self._raises
        return list(self._events)

    def archive_path(self) -> str:
        return "/mnt/data/parquet/stub/"


def _event(source_event_id: str) -> Event:
    now = datetime.now(timezone.utc)
    return Event(
        source="stub",
        source_event_id=source_event_id,
        occurred_at=now,
        fetched_at=now,
        category=Category.MARKET,
        severity=0.1,
        country="US",
        keywords=["stub"],
        payload={"k": "v"},
    )


@pytest.fixture
def global_sqlite_db() -> Iterator[Engine]:
    """Swap the app's global engine for an in-memory SQLite + create schema."""
    engine = db.reset_engine_for_testing("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    db._engine = None  # noqa: SLF001 — reset so next test starts clean
    db._session_factory = None  # noqa: SLF001


def _session_for(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False, future=True)()


def test_run_fetcher_persists_events(global_sqlite_db: Engine) -> None:
    fetcher_registry.register("stub", _StubFetcher([_event(f"x:{i}") for i in range(3)]))
    try:
        result = tasks._run_fetcher_body("stub")
    finally:
        fetcher_registry.deregister("stub")

    assert result == {"fetched": 3, "inserted": 3}
    with _session_for(global_sqlite_db) as session:
        rows = session.execute(select(EventRow)).scalars().all()
        assert len(rows) == 3
        health = session.execute(select(IngestHealthRow)).scalars().all()
        assert len(health) == 1
        assert health[0].source == "stub"
        assert health[0].success_n == 1
        assert health[0].failure_n == 0
        assert health[0].last_success is not None


def test_run_fetcher_idempotent_on_rerun(global_sqlite_db: Engine) -> None:
    fetcher_registry.register("stub", _StubFetcher([_event(f"x:{i}") for i in range(3)]))
    try:
        tasks._run_fetcher_body("stub")
        second = tasks._run_fetcher_body("stub")
    finally:
        fetcher_registry.deregister("stub")

    assert second == {"fetched": 3, "inserted": 0}
    with _session_for(global_sqlite_db) as session:
        rows = session.execute(select(EventRow)).scalars().all()
        assert len(rows) == 3
        health = session.execute(select(IngestHealthRow)).scalars().all()
        assert health[0].success_n == 2


def test_run_fetcher_records_failure_and_reraises(global_sqlite_db: Engine) -> None:
    fetcher_registry.register("stub", _StubFetcher([], raises=RuntimeError("upstream 500")))
    try:
        with pytest.raises(RuntimeError, match="upstream 500"):
            tasks._run_fetcher_body("stub")
    finally:
        fetcher_registry.deregister("stub")

    with _session_for(global_sqlite_db) as session:
        events = session.execute(select(EventRow)).scalars().all()
        assert events == []
        failures = session.execute(select(IngestFailureRow)).scalars().all()
        assert len(failures) == 1
        assert failures[0].error_class == "RuntimeError"
        assert "upstream 500" in (failures[0].error_message or "")
        health = session.execute(select(IngestHealthRow)).scalars().all()
        assert health[0].failure_n == 1
        assert health[0].success_n == 0


def test_unknown_fetcher_raises_key_error(global_sqlite_db: Engine) -> None:
    with pytest.raises(KeyError):
        tasks._run_fetcher_body("does-not-exist")


def test_beat_schedule_covers_all_thesis_core_fetchers() -> None:
    schedule = tasks.app.conf.beat_schedule
    fetcher_names = {
        entry["args"][0]
        for entry in schedule.values()
        if entry["task"] == "app.tasks.run_fetcher"
    }
    assert fetcher_names == {
        "yfinance",
        "fred",
        "gdelt",
        "usgs-quake",
        "gdacs",
        "nasa-firms",
        "eonet",
    }


def test_beat_schedule_includes_composite_worker() -> None:
    schedule = tasks.app.conf.beat_schedule
    composite_entries = [
        entry for entry in schedule.values() if entry["task"] == "app.tasks.compute_composite"
    ]
    assert len(composite_entries) == 1
