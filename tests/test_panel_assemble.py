"""Tests for `app.panel.assemble` — spine + labels + scores → panel records."""

from __future__ import annotations

from datetime import UTC, datetime

from app.panel.assemble import assemble_panel

JAN = datetime(2024, 1, 1, tzinfo=UTC)
FEB = datetime(2024, 2, 1, tzinfo=UTC)

SPINE = [{"country": "SY", "month": JAN}, {"country": "SY", "month": FEB}]


def _label(code: str, month: datetime = JAN, magnitude: float = 12.0) -> dict:
    return {"country": "SY", "bucket_start": month, "label_code": code, "magnitude": magnitude}


def _score(month: datetime = JAN, value: float = 0.7) -> dict:
    return {
        "country": "SY",
        "bucket_start": month,
        "score_value": value,
        "components": {"z": {"market": 0.1, "geopolitical": 2.0, "hazard": -0.3}},
        "method_version": "v1.0",
    }


def test_label_hit_sets_flag_and_magnitude() -> None:
    panel = assemble_panel(SPINE, [_label("P1")], [])
    jan = next(r for r in panel if r["month"] == JAN)
    assert jan["label_p1"] == 1
    assert jan["magnitude_p1"] == 12.0
    assert jan["label_any"] == 1


def test_month_without_label_is_negative() -> None:
    panel = assemble_panel(SPINE, [_label("P1")], [])
    feb = next(r for r in panel if r["month"] == FEB)
    assert feb["label_p1"] == 0
    assert feb["label_p2"] == 0
    assert feb["label_p3"] == 0
    assert feb["label_any"] == 0
    assert feb["magnitude_p1"] is None


def test_multiple_codes_same_month() -> None:
    panel = assemble_panel(SPINE, [_label("P1"), _label("P3", magnitude=40.0)], [])
    jan = next(r for r in panel if r["month"] == JAN)
    assert (jan["label_p1"], jan["label_p2"], jan["label_p3"]) == (1, 0, 1)
    assert jan["magnitude_p3"] == 40.0


def test_score_join_fills_signals_and_composite() -> None:
    panel = assemble_panel(SPINE, [], [_score()])
    jan = next(r for r in panel if r["month"] == JAN)
    assert jan["composite_score"] == 0.7
    assert jan["signal_geopolitical"] == 2.0
    assert jan["signal_market"] == 0.1
    assert jan["signal_hazard"] == -0.3
    assert jan["method_version"] == "v1.0"


def test_month_without_score_has_none_signals() -> None:
    panel = assemble_panel(SPINE, [], [_score(month=JAN)])
    feb = next(r for r in panel if r["month"] == FEB)
    assert feb["composite_score"] is None
    assert feb["signal_market"] is None
    assert feb["method_version"] is None


def test_score_outside_spine_ignored() -> None:
    rogue = _score(month=datetime(2030, 1, 1, tzinfo=UTC))
    panel = assemble_panel(SPINE, [], [rogue])
    assert len(panel) == 2


def test_label_outside_spine_ignored() -> None:
    rogue = _label("P1", month=datetime(1990, 1, 1, tzinfo=UTC))
    panel = assemble_panel(SPINE, [rogue], [])
    assert all(r["label_p1"] == 0 for r in panel)


def test_unknown_label_code_ignored() -> None:
    panel = assemble_panel(SPINE, [_label("P9")], [])
    jan = next(r for r in panel if r["month"] == JAN)
    assert jan["label_any"] == 0
