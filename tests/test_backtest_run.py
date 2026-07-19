"""Tests for backtest orchestration."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.backtest.run import run_backtest


def _stub_series(*_args, **_kwargs):
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(61)]
    physical = [1 + (idx % 2) for idx in range(61)]
    narrative = [1 + (idx % 2) for idx in range(61)]
    physical[30 - 3] = 20
    narrative[30] = 20
    return days, physical, narrative


def _stub_volume(country, start, end, **_kwargs):
    """Narrative volume with a spike on day 30, matching _stub_series."""
    return {start + timedelta(days=i): (20 if i == 30 else 1 + (i % 2)) for i in range(61)}


def test_run_backtest_detects_lead(db_session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.backtest.run.daily_side_counts", _stub_series)
    reg = tmp_path / "events.yaml"
    reg.write_text(
        "events:\n"
        "  - id: jp-test\n"
        "    country: JP\n"
        "    date: 2024-01-31\n"
        "    domain: hazard\n"
        "    source_url: http://x\n"
        "    notes: seeded\n"
    )

    metrics, leads, md, unscorable = run_backtest(
        db_session, reg, backfill=False, volume_fetcher=_stub_volume, cache_dir=None
    )
    assert unscorable == []
    assert leads[0].lead_days == 3
    assert "Lead-Time Gate" in md
    assert metrics.n_events == 1


def test_backfill_is_skipped_when_the_window_is_already_present(db_session, monkeypatch):
    """Re-running must not refetch 60 days of quakes per event (#522).

    The gate is meant to be run repeatedly — new thresholds, new anchors — and
    re-fetching every window each time cost ~5 minutes per event, turning a
    rerun into a 90-minute wait.
    """
    from datetime import date as _date

    from app.backtest.backfill import backfill_event
    from app.backtest.registry import RegistryEvent
    from app.db_models import EventRow

    event = RegistryEvent(
        id="pe-x",
        country="PE",
        date=_date(2026, 5, 1),
        domain="hazard",
        source_url="http://x",
        notes="n",
    )

    class _Counting:
        name = "usgs"

        def __init__(self):
            self.calls = 0

        def fetch_range(self, country, start, end):
            self.calls += 1
            return []

    src = _Counting()
    # Nothing stored yet: the source is consulted.
    backfill_event(db_session, event, [src], skip_if_covered=True)
    assert src.calls == 1

    # A sensor row inside the window means the window is already covered.
    db_session.add(
        EventRow(
            source="usgs-quake",
            source_event_id="seed-1",
            occurred_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            category="hazard",
            country="PE",
            keywords=[],
            payload={"magnitude": 6.1},
        )
    )
    db_session.commit()
    backfill_event(db_session, event, [src], skip_if_covered=True)
    assert src.calls == 1, "already-backfilled window must not be refetched"

    # Default stays the refresh contract: without the flag, the source is asked.
    backfill_event(db_session, event, [src])
    assert src.calls == 2
