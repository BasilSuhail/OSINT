"""Tests for `app.composite.backfill` — historical signal backfill."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.composite.backfill import iter_year_chunks, run_signal_backfill
from app.db_models import ScoreRow


class TestIterYearChunks:
    def test_full_years(self) -> None:
        chunks = iter_year_chunks(date(2015, 1, 1), date(2016, 12, 31))
        assert chunks == [
            (date(2015, 1, 1), date(2015, 12, 31)),
            (date(2016, 1, 1), date(2016, 12, 31)),
        ]

    def test_partial_edges(self) -> None:
        chunks = iter_year_chunks(date(2015, 6, 15), date(2016, 3, 1))
        assert chunks == [
            (date(2015, 6, 15), date(2015, 12, 31)),
            (date(2016, 1, 1), date(2016, 3, 1)),
        ]

    def test_single_year(self) -> None:
        assert iter_year_chunks(date(2020, 2, 1), date(2020, 11, 30)) == [
            (date(2020, 2, 1), date(2020, 11, 30))
        ]

    def test_invalid_range_raises(self) -> None:
        with pytest.raises(ValueError):
            iter_year_chunks(date(2021, 1, 1), date(2020, 1, 1))


def _utc(dt: datetime) -> datetime:
    # SQLite loses tzinfo on DateTime(timezone=True) columns.
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _event(country: str, category: str, severity: float, year: int, month: int) -> dict:
    return {
        "country": country,
        "category": category,
        "severity": severity,
        "occurred_at": datetime(year, month, 15, tzinfo=UTC),
    }


def _fake_market(start: date, end: date) -> list[dict]:
    # Noisy baseline (zero-variance history z-scores to 0 by design) with a
    # clear stress spike in Jun 2015.
    events = []
    for year in (2014, 2015):
        for month in range(1, 13):
            spike = (year, month) == (2015, 6)
            severity = 0.9 if spike else 0.10 + 0.05 * (month % 3)
            events.append(_event("SY", "market", severity, year, month))
    return events


def _fake_hazard(start: date, end: date) -> list[dict]:
    return [_event("SY", "hazard", 0.5, 2015, 6)]


class TestRunSignalBackfill:
    def test_writes_scores_only_inside_score_window(self, db_session: Session) -> None:
        result = run_signal_backfill(
            warmup_start=date(2014, 1, 1),
            scores_start=date(2015, 1, 1),
            end=date(2015, 12, 31),
            market_fetch=_fake_market,
            hazard_fetch=_fake_hazard,
            session=db_session,
        )
        rows = db_session.execute(select(ScoreRow)).scalars().all()
        months = {_utc(row.bucket_start) for row in rows}
        assert all(m >= datetime(2015, 1, 1, tzinfo=UTC) for m in months)
        assert all(m <= datetime(2015, 12, 1, tzinfo=UTC) for m in months)
        assert result["scores_written"] == len(rows) > 0

    def test_warmup_shapes_zscores_but_is_not_written(self, db_session: Session) -> None:
        run_signal_backfill(
            warmup_start=date(2014, 1, 1),
            scores_start=date(2015, 1, 1),
            end=date(2015, 12, 31),
            market_fetch=_fake_market,
            hazard_fetch=_fake_hazard,
            session=db_session,
        )
        rows = {
            _utc(row.bucket_start): row for row in db_session.execute(select(ScoreRow)).scalars()
        }
        june = rows[datetime(2015, 6, 1, tzinfo=UTC)]
        january = rows[datetime(2015, 1, 1, tzinfo=UTC)]
        # June 2015 spike must stand out against the flat 0.1 history.
        assert june.score_value > january.score_value
        assert june.score_value > 0.6

    def test_components_stamped_as_backfill(self, db_session: Session) -> None:
        run_signal_backfill(
            warmup_start=date(2014, 1, 1),
            scores_start=date(2015, 1, 1),
            end=date(2015, 12, 31),
            market_fetch=_fake_market,
            hazard_fetch=_fake_hazard,
            session=db_session,
        )
        row = db_session.execute(select(ScoreRow)).scalars().first()
        assert row.components["backfill"] is True

    def test_rerun_is_idempotent(self, db_session: Session) -> None:
        kwargs = dict(
            warmup_start=date(2014, 1, 1),
            scores_start=date(2015, 1, 1),
            end=date(2015, 12, 31),
            market_fetch=_fake_market,
            hazard_fetch=_fake_hazard,
            session=db_session,
        )
        run_signal_backfill(**kwargs)
        first = len(db_session.execute(select(ScoreRow)).scalars().all())
        run_signal_backfill(**kwargs)
        second = len(db_session.execute(select(ScoreRow)).scalars().all())
        assert first == second

    def test_empty_fetchers_write_nothing(self, db_session: Session) -> None:
        result = run_signal_backfill(
            warmup_start=date(2014, 1, 1),
            scores_start=date(2015, 1, 1),
            end=date(2015, 12, 31),
            market_fetch=lambda s, e: [],
            hazard_fetch=lambda s, e: [],
            session=db_session,
        )
        assert result["scores_written"] == 0
