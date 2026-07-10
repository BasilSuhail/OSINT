"""Tests for `app.onset.eligibility` — calm-window onset filtering (#380)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.onset.eligibility import onset_eligible


def _month(i: int) -> datetime:
    return datetime(2020 + (i // 12), (i % 12) + 1, 1, tzinfo=UTC)


def _panel(labels: dict[str, list[int]]) -> list[dict]:
    return [
        {"country": country, "month": _month(i), "label_any": label}
        for country, series in labels.items()
        for i, label in enumerate(series)
    ]


def test_calm_window_required_before_eligibility() -> None:
    # positive at index 2 → months 3..14 blocked (calm=12); 15+ eligible again.
    series = [0, 0, 1] + [0] * 15
    eligible = onset_eligible(_panel({"AA": series}), calm_months=12)
    assert ("AA", _month(2)) not in eligible
    assert ("AA", _month(14)) not in eligible  # only 11 calm months behind it
    assert ("AA", _month(15)) in eligible  # 12 calm months: 3..14


def test_missing_history_is_not_calm() -> None:
    # Country starts at index 0 — first 12 months lack a full calm window.
    series = [0] * 14
    eligible = onset_eligible(_panel({"AA": series}), calm_months=12)
    assert ("AA", _month(11)) not in eligible
    assert ("AA", _month(12)) in eligible


def test_shorter_calm_window_admits_more() -> None:
    series = [0, 0, 1] + [0] * 15
    strict = onset_eligible(_panel({"AA": series}), calm_months=12)
    loose = onset_eligible(_panel({"AA": series}), calm_months=6)
    assert ("AA", _month(9)) in loose  # calm 3..8
    assert ("AA", _month(9)) not in strict
    assert strict <= loose


def test_chronic_country_never_eligible() -> None:
    eligible = onset_eligible(_panel({"AA": [1] * 20}), calm_months=6)
    assert eligible == set()
