"""Tests for `app.baselines.targets` — horizon targets over the panel."""

from __future__ import annotations

from datetime import UTC, datetime

from app.baselines.targets import build_targets


def _cell(country: str, year: int, month: int, label: int) -> dict:
    return {
        "country": country,
        "month": datetime(year, month, 1, tzinfo=UTC),
        "label_any": label,
    }


def test_k1_positive_next_month() -> None:
    panel = [_cell("SY", 2020, 1, 0), _cell("SY", 2020, 2, 1)]
    targets = build_targets(panel, horizon=1)
    assert targets == {("SY", datetime(2020, 1, 1, tzinfo=UTC)): 1}


def test_k1_negative_next_month() -> None:
    panel = [_cell("SY", 2020, 1, 1), _cell("SY", 2020, 2, 0)]
    targets = build_targets(panel, horizon=1)
    # current month's own label is irrelevant; only [t+1, t+k] counts
    assert targets == {("SY", datetime(2020, 1, 1, tzinfo=UTC)): 0}


def test_k3_catches_positive_at_t_plus_3_not_t_plus_4() -> None:
    panel = [
        _cell("SY", 2020, 1, 0),
        _cell("SY", 2020, 2, 0),
        _cell("SY", 2020, 3, 0),
        _cell("SY", 2020, 4, 1),
        _cell("SY", 2020, 5, 0),
    ]
    targets = build_targets(panel, horizon=3)
    assert targets[("SY", datetime(2020, 1, 1, tzinfo=UTC))] == 1  # t+3 = Apr
    # Feb: window Mar-May contains Apr positive
    assert targets[("SY", datetime(2020, 2, 1, tzinfo=UTC))] == 1


def test_truncated_horizon_rows_excluded() -> None:
    panel = [_cell("SY", 2020, 1, 0), _cell("SY", 2020, 2, 0), _cell("SY", 2020, 3, 0)]
    targets = build_targets(panel, horizon=3)
    # only months with all of [t+1, t+3] inside coverage qualify: none here
    assert targets == {}


def test_year_boundary() -> None:
    panel = [_cell("SY", 2020, 12, 0), _cell("SY", 2021, 1, 1)]
    targets = build_targets(panel, horizon=1)
    assert targets[("SY", datetime(2020, 12, 1, tzinfo=UTC))] == 1


def test_countries_isolated() -> None:
    panel = [
        _cell("SY", 2020, 1, 0),
        _cell("SY", 2020, 2, 0),
        _cell("US", 2020, 1, 0),
        _cell("US", 2020, 2, 1),
    ]
    targets = build_targets(panel, horizon=1)
    assert targets[("SY", datetime(2020, 1, 1, tzinfo=UTC))] == 0
    assert targets[("US", datetime(2020, 1, 1, tzinfo=UTC))] == 1


def test_coverage_gap_breaks_window() -> None:
    # Feb missing from coverage → Jan lacks a complete [t+1] window? No — k=1 needs
    # only t+1; Feb absent means Jan is excluded (window not fully covered).
    panel = [_cell("SY", 2020, 1, 0), _cell("SY", 2020, 3, 1)]
    targets = build_targets(panel, horizon=1)
    assert ("SY", datetime(2020, 1, 1, tzinfo=UTC)) not in targets
    assert ("SY", datetime(2020, 2, 1, tzinfo=UTC)) not in targets
