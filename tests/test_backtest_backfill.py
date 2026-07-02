"""Tests for backfill windowing and idempotence."""

from __future__ import annotations

from datetime import date

from app.backtest.backfill import backfill_event
from app.backtest.registry import RegistryEvent
from app.db_models import EventRow
from app.models import Category, Event


class _StubSource:
    name = "stub"

    def __init__(self, events: list[Event]):
        self._events = events
        self.calls = []

    def fetch_range(self, country: str, start: date, end: date) -> list[Event]:
        self.calls.append((country, start, end))
        return self._events


def _event(i: int) -> Event:
    return Event(
        source="stub",
        source_event_id=f"stub-{i}",
        occurred_at=date(2024, 1, 1).isoformat() + "T12:00:00+00:00",
        fetched_at=date(2024, 1, 2).isoformat() + "T00:00:00+00:00",
        category=Category.HAZARD,
        keywords=[],
        country="JP",
        payload={},
    )


def test_backfill_inserts_and_is_idempotent(db_session):
    event = RegistryEvent("jp", "JP", date(2024, 1, 10), "hazard", "http://x", "")
    src = _StubSource([_event(1), _event(2)])

    first = backfill_event(db_session, event, [src], lookback_days=45, lookahead_days=15)
    db_session.commit()
    assert first == 2
    assert db_session.query(EventRow).count() == 2

    second = backfill_event(db_session, event, [src], lookback_days=45, lookahead_days=15)
    db_session.commit()
    assert second == 2  # rows refreshed on re-run, not duplicated
    assert db_session.query(EventRow).count() == 2


def test_backfill_uses_correct_window(db_session):
    event = RegistryEvent("jp", "JP", date(2024, 1, 10), "hazard", "http://x", "")
    src = _StubSource([])

    backfill_event(db_session, event, [src], lookback_days=45, lookahead_days=15)
    country, start, end = src.calls[0]
    assert country == "JP"
    assert start == date(2023, 11, 26)
    assert end == date(2024, 1, 25)
