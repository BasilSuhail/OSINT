"""Tests for the persisted composite signal history (issue #586).

The composite z-scores each country against its own past. It used to rebuild
that past from the events table on every run, but retention keeps ~30 days, so
183 of 184 countries never reached `MIN_HISTORY = 3` observations and every
live score came out at exactly 0.5. History now outlives the events it was
derived from.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.composite.history import load_signals, merge_signals, persist_signals


def _month(month: int, year: int = 2026) -> datetime:
    return datetime(year, month, 1, tzinfo=UTC)


def test_signals_survive_a_round_trip(db_session: Session) -> None:
    aggregated = {
        ("US", _month(5)): {"hazard": 0.4, "market": 0.1},
        ("PK", _month(5)): {"hazard": 0.9},
    }

    written = persist_signals(aggregated, db_session)
    db_session.commit()

    assert written == 3
    assert load_signals(db_session) == aggregated


def test_a_re_run_updates_rather_than_duplicates(db_session: Session) -> None:
    persist_signals({("US", _month(5)): {"hazard": 0.4}}, db_session)
    db_session.commit()
    persist_signals({("US", _month(5)): {"hazard": 0.7}}, db_session)
    db_session.commit()

    assert load_signals(db_session) == {("US", _month(5)): {"hazard": 0.7}}


def test_history_older_than_the_lookback_is_left_behind(db_session: Session) -> None:
    persist_signals(
        {
            ("US", _month(1, year=2024)): {"hazard": 0.2},
            ("US", _month(5)): {"hazard": 0.4},
        },
        db_session,
    )
    db_session.commit()

    loaded = load_signals(db_session, since=_month(1))

    assert list(loaded) == [("US", _month(5))]


def test_the_current_run_wins_over_stored_history(db_session: Session) -> None:
    # The month in progress is recomputed from live events every run; the stored
    # copy of it is one run stale by definition.
    stored = {("US", _month(5)): {"hazard": 0.4}, ("US", _month(6)): {"hazard": 0.5}}
    current = {("US", _month(6)): {"hazard": 0.8}, ("PK", _month(6)): {"hazard": 0.3}}

    merged = merge_signals(stored, current)

    assert merged == {
        ("US", _month(5)): {"hazard": 0.4},
        ("US", _month(6)): {"hazard": 0.8},
        ("PK", _month(6)): {"hazard": 0.3},
    }


def test_a_domain_missing_from_the_current_run_keeps_its_stored_value(
    db_session: Session,
) -> None:
    # A quiet month for one domain must not erase what the others recorded.
    stored = {("US", _month(6)): {"hazard": 0.4, "market": 0.2}}
    current = {("US", _month(6)): {"hazard": 0.9}}

    assert merge_signals(stored, current) == {("US", _month(6)): {"hazard": 0.9, "market": 0.2}}
