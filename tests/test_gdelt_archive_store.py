"""Storing archive counts and reading them back as a narrative series (#555)."""

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.backtest import gdelt_archive
from app.db_models import Base, GdeltDailyVolumeRow


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _counts(**kw):
    return {("UA", date(2026, 6, 18)): gdelt_archive.DayCount(**kw)}


def _ingest(session, counts, days):
    gdelt_archive.store_counts(session, counts)
    for day in days:
        gdelt_archive.mark_day_ingested(session, day, files_ok=96, files_missing=0)


def test_store_writes_one_row_per_country_day():
    session = _session()
    assert gdelt_archive.store_counts(session, _counts(events=4, mentions=40)) == 1
    row = session.execute(select(GdeltDailyVolumeRow)).scalar_one()
    assert (row.country, row.day, row.events, row.mentions) == ("UA", date(2026, 6, 18), 4, 40)
    assert row.method_version == gdelt_archive.METHOD_VERSION


def test_store_is_idempotent_and_overwrites_a_partial_day():
    # A day is only correct once every file for it has been walked, and a run
    # can be interrupted mid-day. Re-running must replace the partial count,
    # not add to it — otherwise a resumed backfill silently doubles a day.
    session = _session()
    gdelt_archive.store_counts(session, _counts(events=4, mentions=40))
    gdelt_archive.store_counts(session, _counts(events=9, mentions=90))
    row = session.execute(select(GdeltDailyVolumeRow)).scalar_one()
    assert (row.events, row.mentions) == (9, 90)


def test_daily_volume_reads_back_a_date_indexed_series():
    session = _session()
    _ingest(
        session,
        {
            ("UA", date(2026, 6, 18)): gdelt_archive.DayCount(events=4, mentions=40),
            ("UA", date(2026, 6, 19)): gdelt_archive.DayCount(events=7, mentions=70),
            ("JP", date(2026, 6, 18)): gdelt_archive.DayCount(events=1, mentions=10),
        },
        [date(2026, 6, 18), date(2026, 6, 19)],
    )
    assert gdelt_archive.daily_volume(session, "UA", date(2026, 6, 18), date(2026, 6, 19)) == {
        date(2026, 6, 18): 40,
        date(2026, 6, 19): 70,
    }


def test_daily_volume_can_read_the_event_count_instead():
    session = _session()
    _ingest(session, _counts(events=4, mentions=40), [date(2026, 6, 18)])
    assert gdelt_archive.daily_volume(
        session, "UA", date(2026, 6, 18), date(2026, 6, 18), measure="events"
    ) == {date(2026, 6, 18): 4}


def test_a_quiet_country_day_reads_as_zero_not_as_a_gap():
    # The day was walked and this country simply had no coverage. That is a
    # real zero, and it is what makes a narrative spike a spike.
    session = _session()
    _ingest(session, _counts(events=4, mentions=40), [date(2026, 6, 18), date(2026, 6, 19)])
    assert gdelt_archive.daily_volume(session, "UA", date(2026, 6, 18), date(2026, 6, 19)) == {
        date(2026, 6, 18): 40,
        date(2026, 6, 19): 0,
    }


def test_daily_volume_raises_when_the_window_was_never_ingested():
    # An empty narrative series is exactly what produced a confident FAIL
    # against a series that was never fetched (see app/backtest/narrative.py).
    # An un-ingested window must never masquerade as a quiet one.
    session = _session()
    with pytest.raises(gdelt_archive.ArchiveWindowMissingError):
        gdelt_archive.daily_volume(session, "UA", date(2026, 6, 18), date(2026, 6, 19))


def test_daily_volume_raises_when_the_window_is_only_partly_ingested():
    session = _session()
    _ingest(session, _counts(events=4, mentions=40), [date(2026, 6, 18)])
    with pytest.raises(gdelt_archive.ArchiveWindowMissingError) as excinfo:
        gdelt_archive.daily_volume(session, "UA", date(2026, 6, 18), date(2026, 6, 20))
    assert "2026-06-19" in str(excinfo.value)


def test_a_day_whose_files_mostly_failed_does_not_count_as_ingested():
    # Half a day's files is half a day's volume, which would read as a dip the
    # sensor side never caused.
    session = _session()
    gdelt_archive.store_counts(session, _counts(events=4, mentions=40))
    gdelt_archive.mark_day_ingested(session, date(2026, 6, 18), files_ok=40, files_missing=56)
    with pytest.raises(gdelt_archive.ArchiveWindowMissingError):
        gdelt_archive.daily_volume(session, "UA", date(2026, 6, 18), date(2026, 6, 18))


def test_mark_day_ingested_is_idempotent():
    session = _session()
    gdelt_archive.mark_day_ingested(session, date(2026, 6, 18), files_ok=96, files_missing=0)
    gdelt_archive.mark_day_ingested(session, date(2026, 6, 18), files_ok=95, files_missing=1)
    assert gdelt_archive.ingested_days(session, date(2026, 6, 18), date(2026, 6, 18)) == {
        date(2026, 6, 18)
    }
