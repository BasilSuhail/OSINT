"""Tests for `app.tasks._run_fetcher_body`.

The Celery layer is thin — Celery just calls the body function. Tests target
the body directly so the suite stays hermetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from app import db, fetcher_registry, tasks
from app.db_models import Base, EventRow, IngestFailureRow, IngestHealthRow
from app.ingest.outcome import IngestOutcome
from app.models import Category, Event
from app.sources.base import FetchBatch, Fetcher, SourceMisconfiguredError


class _StubFetcher(Fetcher):
    name = "stub"
    queue = "fast"

    def __init__(
        self,
        events: list[Event],
        *,
        raises: Exception | None = None,
        unchanged: bool = False,
    ) -> None:
        self._events = events
        self._raises = raises
        self._unchanged = unchanged

    def fetch(self) -> list[Event] | FetchBatch:
        if self._raises is not None:
            raise self._raises
        if self._unchanged:
            return FetchBatch(unchanged=True)
        return list(self._events)

    def archive_path(self) -> str:
        return "/mnt/data/parquet/stub/"


def _event(source_event_id: str) -> Event:
    now = datetime.now(UTC)
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
    db._engine = None
    db._session_factory = None


def _session_for(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False, future=True)()


def test_run_fetcher_persists_events(global_sqlite_db: Engine) -> None:
    fetcher_registry.register("stub", _StubFetcher([_event(f"x:{i}") for i in range(3)]))
    try:
        result = tasks._run_fetcher_body("stub")
    finally:
        fetcher_registry.deregister("stub")

    assert result == {
        "state": "new_data",
        "fetched": 3,
        "accepted": 3,
        "affected": 3,
        "inserted": 3,
        "rejected": 0,
    }
    with _session_for(global_sqlite_db) as session:
        rows = session.execute(select(EventRow)).scalars().all()
        assert len(rows) == 3
        health = session.execute(select(IngestHealthRow)).scalars().all()
        assert len(health) == 1
        assert health[0].source == "stub"
        assert health[0].success_n == 1
        assert health[0].failure_n == 0
        assert health[0].new_data_n == 1
        assert health[0].fetched_rows == 3
        assert health[0].accepted_rows == 3
        assert health[0].inserted_rows == 3
        assert health[0].last_state == "new_data"
        assert health[0].last_output is not None
        assert health[0].last_success is not None


def test_run_fetcher_idempotent_on_rerun(global_sqlite_db: Engine) -> None:
    fetcher_registry.register("stub", _StubFetcher([_event(f"x:{i}") for i in range(3)]))
    try:
        tasks._run_fetcher_body("stub")
        second = tasks._run_fetcher_body("stub")
    finally:
        fetcher_registry.deregister("stub")

    assert second == {
        "state": "unchanged",
        "fetched": 3,
        "accepted": 3,
        "affected": 3,
        "inserted": 0,
        "rejected": 0,
    }
    with _session_for(global_sqlite_db) as session:
        rows = session.execute(select(EventRow)).scalars().all()
        assert len(rows) == 3
        health = session.execute(select(IngestHealthRow)).scalars().all()
        assert health[0].success_n == 2
        assert health[0].new_data_n == 1
        assert health[0].unchanged_n == 1
        assert health[0].inserted_rows == 3
        assert health[0].accepted_rows == 6


def test_empty_output_is_not_recorded_as_success(global_sqlite_db: Engine) -> None:
    fetcher_registry.register("stub", _StubFetcher([]))
    try:
        result = tasks._run_fetcher_body("stub")
    finally:
        fetcher_registry.deregister("stub")

    assert result["state"] == "empty"
    with _session_for(global_sqlite_db) as session:
        health = session.execute(select(IngestHealthRow)).scalar_one()
        assert health.success_n == 0
        assert health.empty_n == 1
        assert health.last_success is None
        assert health.last_output is None
        assert health.last_checked is not None


def test_static_unchanged_input_is_a_successful_check(global_sqlite_db: Engine) -> None:
    fetcher_registry.register("stub", _StubFetcher([], unchanged=True))
    try:
        result = tasks._run_fetcher_body("stub")
    finally:
        fetcher_registry.deregister("stub")

    assert result["state"] == "unchanged"
    with _session_for(global_sqlite_db) as session:
        health = session.execute(select(IngestHealthRow)).scalar_one()
        assert health.success_n == 1
        assert health.unchanged_n == 1
        assert health.last_success is not None
        assert health.last_output is None


def test_new_daily_row_carries_prior_freshness_clocks(global_sqlite_db: Engine) -> None:
    first = datetime(2026, 8, 8, 23, 59, tzinfo=UTC)
    second = datetime(2026, 8, 9, 0, 1, tzinfo=UTC)
    with _session_for(global_sqlite_db) as session:
        tasks._record_outcome(
            session,
            source="stub",
            result=IngestOutcome(
                state="new_data",
                fetched=1,
                accepted=1,
                affected=1,
                inserted=1,
            ),
            now=first,
        )
        session.commit()
        tasks._record_outcome(
            session,
            source="stub",
            result=IngestOutcome(state="empty"),
            now=second,
        )
        session.commit()

        latest = session.get(IngestHealthRow, ("stub", second.date()))
        assert latest is not None
        assert latest.last_success is not None
        assert latest.last_output is not None
        assert latest.last_checked is not None
        assert latest.last_success.replace(tzinfo=UTC) == first
        assert latest.last_output.replace(tzinfo=UTC) == first
        assert latest.last_checked.replace(tzinfo=UTC) == second


def test_all_stale_batch_is_empty_with_rejections_preserved(global_sqlite_db: Engine) -> None:
    stale = _event("stale").model_copy(
        update={"occurred_at": datetime.now(UTC) - timedelta(days=365)}
    )
    fetcher_registry.register("stub", _StubFetcher([stale]))
    try:
        result = tasks._run_fetcher_body("stub")
    finally:
        fetcher_registry.deregister("stub")

    assert result["state"] == "empty"
    assert result["fetched"] == result["rejected"] == result["rejected_stale"] == 1
    assert result["accepted"] == result["inserted"] == 0
    with _session_for(global_sqlite_db) as session:
        health = session.execute(select(IngestHealthRow)).scalar_one()
        assert health.empty_n == 1
        assert health.rejected_rows == 1
        failure = session.execute(select(IngestFailureRow)).scalar_one()
        assert failure.error_class == "StaleEventsRejected"


def test_missing_configuration_has_its_own_terminal_state(global_sqlite_db: Engine) -> None:
    fetcher_registry.register(
        "stub", _StubFetcher([], raises=SourceMisconfiguredError("required input missing"))
    )
    try:
        result = tasks._run_fetcher_body("stub")
    finally:
        fetcher_registry.deregister("stub")

    assert result["state"] == "misconfigured"
    with _session_for(global_sqlite_db) as session:
        health = session.execute(select(IngestHealthRow)).scalar_one()
        assert health.misconfigured_n == 1
        assert health.success_n == health.failure_n == 0
        assert health.last_state == "misconfigured"
        assert session.execute(select(IngestFailureRow)).scalars().all() == []


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
        assert health[0].last_state == "failed"


def test_persistence_failure_is_recorded_and_reraised(
    global_sqlite_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetcher_registry.register("stub", _StubFetcher([_event("x")]))
    monkeypatch.setattr(
        tasks,
        "upsert_events_report",
        lambda _events, _session: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    try:
        with pytest.raises(RuntimeError, match="database unavailable"):
            tasks._run_fetcher_body("stub")
    finally:
        fetcher_registry.deregister("stub")

    with _session_for(global_sqlite_db) as session:
        health = session.execute(select(IngestHealthRow)).scalar_one()
        assert health.last_state == "failed"
        assert health.failure_n == 1
        assert health.last_fetched == 1
        assert health.fetched_rows == 1
        assert health.last_accepted == 0
        assert session.execute(select(IngestFailureRow)).scalar_one().error_class == "RuntimeError"


def test_persistence_failure_preserves_known_rejections(
    global_sqlite_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _event("old").model_copy(update={"occurred_at": datetime.now(UTC) - timedelta(days=31)})
    fetcher_registry.register("stub", _StubFetcher([_event("fresh"), old]))
    monkeypatch.setattr(
        tasks,
        "upsert_events_report",
        lambda _events, _session: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    try:
        with pytest.raises(RuntimeError, match="database unavailable"):
            tasks._run_fetcher_body("stub")
    finally:
        fetcher_registry.deregister("stub")

    with _session_for(global_sqlite_db) as session:
        health = session.execute(select(IngestHealthRow)).scalar_one()
        assert health.last_state == "failed"
        assert health.last_fetched == 2
        assert health.last_rejected == 1
        assert health.fetched_rows == 2
        assert health.rejected_rows == 1
        assert health.accepted_rows == 0


def test_unknown_fetcher_raises_key_error(global_sqlite_db: Engine) -> None:
    with pytest.raises(KeyError):
        tasks._run_fetcher_body("does-not-exist")


_THESIS_CORE_FETCHERS = {
    "yfinance",
    "fred",
    "gdelt",
    "acled",
    "emdat",
    "usgs-quake",
    "gdacs",
    "nasa-firms",
    "eonet",
}

_LAYER3_NEWS_FETCHERS = {
    "rss-bbc-world",
    "rss-bbc-uk",
    "rss-reuters-world",
    "rss-dawn",
    "rss-guardian-world",
    "rss-geo-english",
}


def test_beat_schedule_covers_all_thesis_core_fetchers() -> None:
    schedule = tasks.app.conf.beat_schedule
    fetcher_names = {
        entry["args"][0] for entry in schedule.values() if entry["task"] == "app.tasks.run_fetcher"
    }
    # Project-core sources must all be scheduled. Layer-3 sources (RSS,
    # uk-police) can come and go without breaking this assertion.
    assert _THESIS_CORE_FETCHERS.issubset(fetcher_names)


def test_beat_schedule_covers_all_layer3_news_fetchers() -> None:
    schedule = tasks.app.conf.beat_schedule
    fetcher_names = {
        entry["args"][0] for entry in schedule.values() if entry["task"] == "app.tasks.run_fetcher"
    }
    assert _LAYER3_NEWS_FETCHERS.issubset(fetcher_names)


def test_beat_schedule_includes_uk_police_layer3() -> None:
    schedule = tasks.app.conf.beat_schedule
    fetcher_names = {
        entry["args"][0] for entry in schedule.values() if entry["task"] == "app.tasks.run_fetcher"
    }
    assert "uk-police" in fetcher_names


def test_beat_schedule_includes_composite_worker() -> None:
    schedule = tasks.app.conf.beat_schedule
    composite_entries = [
        entry for entry in schedule.values() if entry["task"] == "app.tasks.compute_composite"
    ]
    assert len(composite_entries) == 1


def test_optional_heavy_tasks_skip_when_runtime_busy(monkeypatch) -> None:
    monkeypatch.setattr(tasks.runtime_load, "busy_reason", lambda: "brain-qa-eval active")

    assert tasks.cluster_stories() == {
        "skipped": True,
        "reason": "brain-qa-eval active",
    }


def test_footprint_task_uses_configured_limit(monkeypatch) -> None:
    captured: dict[str, int] = {}
    monkeypatch.setattr(tasks.runtime_load, "busy_reason", lambda: None)
    monkeypatch.setattr(tasks.settings, "footprint_enrichment_limit", 17)
    monkeypatch.setattr(
        tasks,
        "_enrich_footprints_body",
        lambda *, limit: captured.setdefault("limit", limit) or {"ok": 1},
    )

    tasks.enrich_footprints()

    assert captured == {"limit": 17}


def test_named_place_task_is_scheduled_and_uses_configured_limit(monkeypatch) -> None:
    entry = tasks.app.conf.beat_schedule["enrich-news-places-30min"]
    assert entry["task"] == "app.tasks.enrich_news_places"

    captured: dict[str, int] = {}
    monkeypatch.setattr(tasks.runtime_load, "busy_reason", lambda: None)
    monkeypatch.setattr(tasks.settings, "place_enrichment_limit", 7)
    monkeypatch.setattr(
        tasks,
        "_enrich_news_places_body",
        lambda *, limit: captured.setdefault("limit", limit) or {"ok": 1},
    )

    tasks.enrich_news_places_task()

    assert captured == {"limit": 7}
