"""Tests for `app.persistence`.

Schema is created in-memory via SQLite per the conftest fixture. Postgres-only
behaviour (JSONB containment operators, GIN indexes) is covered by Alembic
applying the migration against the real Postgres in CI.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow
from app.models import Category, Event
from app.persistence import _event_to_row, upsert_events


def _make_event(source_event_id: str, *, severity: float = 0.5) -> Event:
    now = datetime.now(UTC)
    return Event(
        source="yfinance",
        source_event_id=source_event_id,
        occurred_at=now,
        fetched_at=now,
        category=Category.MARKET,
        severity=severity,
        country="US",
        keywords=["SPY", "etf"],
        payload={"ticker": "SPY", "close": 500.0},
    )


class TestEventToRow:
    def test_converts_all_fields(self) -> None:
        event = _make_event("SPY:2026-06-18T00:00:00+00:00")
        row = _event_to_row(event)
        assert row["source"] == "yfinance"
        assert row["source_event_id"] == "SPY:2026-06-18T00:00:00+00:00"
        assert row["category"] == "market"
        assert row["severity"] == 0.5
        assert row["country"] == "US"
        assert row["payload"] == {"ticker": "SPY", "close": 500.0}
        assert row["keywords"] == ["SPY", "etf"]

    def test_handles_none_severity_and_confidence(self) -> None:
        event = _make_event("SPY:2026-06-18T00:00:00+00:00", severity=0.0)
        event_obj = event.model_copy(update={"severity": None, "confidence": None})
        row = _event_to_row(event_obj)
        assert row["severity"] is None
        assert row["confidence"] is None


class TestUpsertEvents:
    def test_empty_list_returns_zero(self, db_session: Session) -> None:
        assert upsert_events([], db_session) == 0

    def test_inserts_new_events(self, db_session: Session) -> None:
        events = [_make_event(f"SPY:{i}") for i in range(5)]
        inserted = upsert_events(events, db_session)
        db_session.commit()

        assert inserted == 5
        rows = db_session.execute(select(EventRow)).scalars().all()
        assert len(rows) == 5

    def test_duplicate_inserts_are_dropped(self, db_session: Session) -> None:
        events = [_make_event(f"SPY:{i}") for i in range(3)]

        first = upsert_events(events, db_session)
        db_session.commit()

        # Re-run the same payload — every row should be a conflict.
        second = upsert_events(events, db_session)
        db_session.commit()

        rows = db_session.execute(select(EventRow)).scalars().all()
        assert first == 3
        assert second == 0
        assert len(rows) == 3

    def test_mixed_new_and_duplicate_inserts_only_the_new(self, db_session: Session) -> None:
        original = [_make_event(f"SPY:{i}") for i in range(3)]
        upsert_events(original, db_session)
        db_session.commit()

        # Two of the three already exist; one is new.
        mixed = [_make_event("SPY:1"), _make_event("SPY:2"), _make_event("SPY:new")]
        added = upsert_events(mixed, db_session)
        db_session.commit()

        rows = db_session.execute(select(EventRow)).scalars().all()
        assert added == 1
        assert len(rows) == 4

    def test_different_sources_same_id_coexist(self, db_session: Session) -> None:
        # The dedup key is (source, source_event_id) — same id under different
        # sources must coexist.
        yfin = _make_event("X:1")
        fred = _make_event("X:1").model_copy(update={"source": "fred"})
        upsert_events([yfin, fred], db_session)
        db_session.commit()

        rows = db_session.execute(select(EventRow)).scalars().all()
        assert len(rows) == 2
        assert {r.source for r in rows} == {"yfinance", "fred"}

    def test_large_payload_batches_under_param_cap(self, db_session: Session) -> None:
        # Postgres caps a single statement at 65 535 bound parameters; with 12
        # columns per Event a non-batched upsert would blow the cap somewhere
        # above 5 461 rows. Verify a 50 000-row payload still upserts cleanly
        # (here against SQLite, but the same batching keeps Postgres safe).
        events = [_make_event(f"BULK:{i}") for i in range(50_000)]
        inserted = upsert_events(events, db_session, batch_size=1000)
        db_session.commit()

        assert inserted == 50_000
        rows = db_session.execute(select(EventRow)).scalars().all()
        assert len(rows) == 50_000

    def test_batch_size_must_be_positive(self, db_session: Session) -> None:
        import pytest

        with pytest.raises(ValueError):
            upsert_events([_make_event("X")], db_session, batch_size=0)
