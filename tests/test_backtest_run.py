"""Tests for backtest orchestration."""

from __future__ import annotations

from datetime import date, timedelta

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
