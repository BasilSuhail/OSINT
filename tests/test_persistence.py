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
from app.persistence import ENRICHMENT_PAYLOAD_KEYS, _event_to_row, upsert_events


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

    def test_reupsert_refreshes_existing(self, db_session: Session) -> None:
        events = [_make_event(f"SPY:{i}") for i in range(3)]
        first = upsert_events(events, db_session)
        db_session.commit()

        # Re-run the same keys with a changed mutable field — every row is a
        # conflict and must be REFRESHED (snapshot feeds re-publish active events).
        updated = [_make_event(f"SPY:{i}", severity=0.9) for i in range(3)]
        second = upsert_events(updated, db_session)
        db_session.commit()

        rows = db_session.execute(select(EventRow)).scalars().all()
        assert first == 3
        assert second == 3  # refreshed, not skipped
        assert len(rows) == 3  # no duplicate rows created
        assert all(r.severity == 0.9 for r in rows)  # mutable field updated

    def test_refresh_keeps_locally_enriched_payload_keys(self, db_session: Session) -> None:
        # A refresh used to overwrite payload wholesale, so every enrichment key
        # we add ourselves (footprint geometry, sentiment, NER) was wiped on the
        # next fetch. GDACS re-publishes an active hazard every 15 min, which is
        # why long-running droughts never kept their real polygon (#604).
        upsert_events([_make_event("SPY:1")], db_session)
        db_session.commit()
        row = db_session.execute(select(EventRow)).scalars().one()
        row.payload = {**row.payload, "footprint_geojson": {"features": [1]}}
        db_session.commit()

        upsert_events([_make_event("SPY:1", severity=0.9)], db_session)
        db_session.commit()
        db_session.expire_all()

        row = db_session.execute(select(EventRow)).scalars().one()
        assert row.payload["footprint_geojson"] == {"features": [1]}, "enrichment was wiped"
        assert row.severity == 0.9, "upstream refresh no longer lands"

    def test_every_enrichment_owned_key_survives_a_refresh(self, db_session: Session) -> None:
        # The #604 trap: `payload` joined _REFRESH_COLS in a change that was
        # right on its own, and silently deleted what enrichment had written.
        # This walks the registry so adding an enricher without protecting its
        # key, or reverting to replace semantics, fails here instead of quietly
        # emptying the map weeks later.
        upsert_events([_make_event("SPY:1")], db_session)
        db_session.commit()
        row = db_session.execute(select(EventRow)).scalars().one()
        row.payload = {**row.payload, **{k: f"enriched-{k}" for k in ENRICHMENT_PAYLOAD_KEYS}}
        db_session.commit()

        upsert_events([_make_event("SPY:1", severity=0.9)], db_session)
        db_session.commit()
        db_session.expire_all()

        row = db_session.execute(select(EventRow)).scalars().one()
        survivors = {k: row.payload.get(k) for k in ENRICHMENT_PAYLOAD_KEYS}
        assert survivors == {k: f"enriched-{k}" for k in ENRICHMENT_PAYLOAD_KEYS}
        assert row.severity == 0.9, "upstream refresh no longer lands"

    def test_the_registry_is_not_empty(self) -> None:
        # A registry that quietly empties would make the test above vacuous.
        assert len(ENRICHMENT_PAYLOAD_KEYS) >= 5
        assert "footprint_geojson" in ENRICHMENT_PAYLOAD_KEYS

    def test_refresh_lets_upstream_win_on_shared_keys(self, db_session: Session) -> None:
        upsert_events([_make_event("SPY:1")], db_session)
        db_session.commit()
        row = db_session.execute(select(EventRow)).scalars().one()
        row.payload = {**row.payload, "close": 1.0, "alert_level": "Green"}
        db_session.commit()

        upsert_events([_make_event("SPY:1")], db_session)
        db_session.commit()
        db_session.expire_all()

        row = db_session.execute(select(EventRow)).scalars().one()
        assert row.payload["close"] == 500.0, "stale local value shadowed the upstream one"
        assert row.payload["alert_level"] == "Green"

    def test_mixed_new_and_existing_all_affected(self, db_session: Session) -> None:
        original = [_make_event(f"SPY:{i}") for i in range(3)]
        upsert_events(original, db_session)
        db_session.commit()

        # Two of the three exist (refreshed); one is new (inserted) → 3 affected.
        mixed = [_make_event("SPY:1"), _make_event("SPY:2"), _make_event("SPY:new")]
        affected = upsert_events(mixed, db_session)
        db_session.commit()

        rows = db_session.execute(select(EventRow)).scalars().all()
        assert affected == 3
        assert len(rows) == 4

    def test_intra_batch_duplicate_keeps_last(self, db_session: Session) -> None:
        # ON CONFLICT DO UPDATE cannot touch the same key twice in one statement,
        # so a duplicate id within a single batch collapses to the last value.
        batch = [_make_event("SPY:dup", severity=0.1), _make_event("SPY:dup", severity=0.8)]
        upsert_events(batch, db_session)
        db_session.commit()
        rows = db_session.execute(select(EventRow)).scalars().all()
        assert len(rows) == 1
        assert rows[0].severity == 0.8

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


class TestUpsertEventsPublish:
    def test_upsert_publishes_inserted_count(self, db_session: Session) -> None:
        from unittest.mock import patch

        events = [_make_event("a"), _make_event("b")]
        with patch("app.persistence.publish_new_events") as pub:
            inserted = upsert_events(events, db_session)
        assert inserted == 2
        pub.assert_called_once_with(2)

    def test_upsert_publish_failure_does_not_raise(self, db_session: Session) -> None:
        from unittest.mock import patch

        with patch("app.persistence.publish_new_events", side_effect=RuntimeError("redis down")):
            inserted = upsert_events([_make_event("x")], db_session)
        assert inserted == 1  # ingestion survives a dead Redis
