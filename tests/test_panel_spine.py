"""Tests for `app.panel.spine` — per-country coverage windows → (country, month) grid."""

from __future__ import annotations

from datetime import UTC, datetime

from app.panel.spine import build_spine, coverage_windows


def _row(country: str, week: datetime) -> dict:
    return {"country": country, "week": week, "event_type": "Battles", "events": 1, "fatalities": 0}


def test_coverage_windows_span_first_to_last_observed_month() -> None:
    rows = [
        _row("SY", datetime(2020, 3, 7, tzinfo=UTC)),
        _row("SY", datetime(2021, 11, 20, tzinfo=UTC)),
        _row("US", datetime(2024, 5, 4, tzinfo=UTC)),
    ]
    windows = coverage_windows(rows)
    assert windows["SY"] == (datetime(2020, 3, 1, tzinfo=UTC), datetime(2021, 11, 1, tzinfo=UTC))
    assert windows["US"] == (datetime(2024, 5, 1, tzinfo=UTC), datetime(2024, 5, 1, tzinfo=UTC))


def test_build_spine_iterates_months_inclusive_across_year_boundary() -> None:
    windows = {"SY": (datetime(2023, 11, 1, tzinfo=UTC), datetime(2024, 2, 1, tzinfo=UTC))}
    spine = build_spine(windows)
    assert [(r["country"], r["month"]) for r in spine] == [
        ("SY", datetime(2023, 11, 1, tzinfo=UTC)),
        ("SY", datetime(2023, 12, 1, tzinfo=UTC)),
        ("SY", datetime(2024, 1, 1, tzinfo=UTC)),
        ("SY", datetime(2024, 2, 1, tzinfo=UTC)),
    ]


def test_build_spine_single_month_country() -> None:
    windows = {"US": (datetime(2024, 5, 1, tzinfo=UTC), datetime(2024, 5, 1, tzinfo=UTC))}
    assert len(build_spine(windows)) == 1


def test_build_spine_countries_do_not_share_windows() -> None:
    windows = {
        "SY": (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 3, 1, tzinfo=UTC)),
        "US": (datetime(2024, 2, 1, tzinfo=UTC), datetime(2024, 2, 1, tzinfo=UTC)),
    }
    spine = build_spine(windows)
    assert sum(1 for r in spine if r["country"] == "SY") == 3
    assert sum(1 for r in spine if r["country"] == "US") == 1
    assert spine == sorted(spine, key=lambda r: (r["country"], r["month"]))
