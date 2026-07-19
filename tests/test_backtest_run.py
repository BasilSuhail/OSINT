"""Tests for backtest orchestration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.backtest.run import run_backtest


def _stub_intensity(_session, _country, start, end):
    """Daily physical intensity, derived from the requested window so it cannot
    drift out of step with the runner's lookback (#526). Values are magnitudes
    since #528, not row counts."""
    span = (end - start).days + 1
    days = [start + timedelta(days=i) for i in range(span)]
    physical = [4.0 + (i % 2) * 0.1 for i in range(span)]
    physical[span - 34] = 7.2
    return days, physical


def _stub_volume(country, start, end, **_kwargs):
    """Narrative volume spiking three days after the physical peak."""
    span = (end - start).days + 1
    spike = span - 31
    return {start + timedelta(days=i): (900 if i == spike else 100 + (i % 2)) for i in range(span)}


def test_run_backtest_detects_lead(db_session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.backtest.run.daily_physical_intensity", _stub_intensity)
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


def test_lookback_leaves_room_for_the_full_lead_window():
    """Warmup must not eat the span being analysed (#526).

    A z-score needs a full ROLLING_WINDOW_DAYS baseline before it exists, so a
    45-day lookback would leave only ~17 usable days and silently clip
    MAX_LEAD_LOOKBACK_DAYS to less than its configured 21.
    """
    from app.backtest import run as run_mod
    from app.divergence.config import MAX_LEAD_LOOKBACK_DAYS, ROLLING_WINDOW_DAYS

    usable_before_event = run_mod._LOOKBACK_DAYS - ROLLING_WINDOW_DAYS
    assert usable_before_event >= MAX_LEAD_LOOKBACK_DAYS
