"""Tests for the pure helpers in `scripts.backfill`.

The HTTP-bound paths (full GDELT 2-year walk, FRED full history,
yfinance live ticker dump) are covered by manual runs documented in the
PR body — not in unit tests, because they hit live upstreams and cost
many minutes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from scripts.backfill import _gdelt_timestamps


class TestGdeltTimestamps:
    def test_single_15min_window(self) -> None:
        start = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        end = datetime(2026, 6, 1, 12, 15, tzinfo=UTC)
        stamps = _gdelt_timestamps(start, end)
        assert stamps == ["20260601120000"]

    def test_one_hour_yields_four_stamps(self) -> None:
        start = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        end = datetime(2026, 6, 1, 13, 0, tzinfo=UTC)
        stamps = _gdelt_timestamps(start, end)
        assert stamps == [
            "20260601120000",
            "20260601121500",
            "20260601123000",
            "20260601124500",
        ]

    def test_misaligned_start_rounds_down(self) -> None:
        # 12:07 should round down to 12:00 so the grid stays canonical.
        start = datetime(2026, 6, 1, 12, 7, tzinfo=UTC)
        end = datetime(2026, 6, 1, 12, 30, tzinfo=UTC)
        stamps = _gdelt_timestamps(start, end)
        assert stamps[0] == "20260601120000"
        assert stamps[-1] == "20260601121500"

    def test_full_day_yields_96_stamps(self) -> None:
        start = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
        end = datetime(2026, 6, 2, 0, 0, tzinfo=UTC)
        stamps = _gdelt_timestamps(start, end)
        assert len(stamps) == 96  # 24h x 4 slots/h

    def test_empty_range(self) -> None:
        ts = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        assert _gdelt_timestamps(ts, ts) == []
