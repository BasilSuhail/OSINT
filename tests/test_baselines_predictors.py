"""Tests for `app.baselines.predictors` — B0 random, B1 persistence, B2 base rate."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.baselines.predictors import (
    score_base_rate,
    score_composite,
    score_persistence,
    score_random,
)


def _cell(country: str, year: int, month: int, label: int) -> dict:
    return {
        "country": country,
        "month": datetime(year, month, 1, tzinfo=UTC),
        "label_any": label,
    }


PANEL = [
    _cell("SY", 2020, 1, 1),
    _cell("SY", 2020, 2, 0),
    _cell("SY", 2020, 3, 1),
    _cell("US", 2020, 1, 0),
    _cell("US", 2020, 2, 0),
]


class TestRandom:
    def test_deterministic_under_seed(self) -> None:
        a = score_random(PANEL, seed=42)
        b = score_random(PANEL, seed=42)
        assert a == b

    def test_scores_in_unit_interval(self) -> None:
        assert all(0.0 <= v <= 1.0 for v in score_random(PANEL, seed=1).values())

    def test_one_score_per_cell(self) -> None:
        assert len(score_random(PANEL, seed=1)) == 5


class TestPersistence:
    def test_score_is_current_label(self) -> None:
        scores = score_persistence(PANEL)
        assert scores[("SY", datetime(2020, 1, 1, tzinfo=UTC))] == 1.0
        assert scores[("SY", datetime(2020, 2, 1, tzinfo=UTC))] == 0.0


class TestBaseRate:
    def test_expanding_mean_includes_current_month(self) -> None:
        scores = score_base_rate(PANEL)
        # SY: Jan → 1/1, Feb → 1/2, Mar → 2/3
        assert scores[("SY", datetime(2020, 1, 1, tzinfo=UTC))] == 1.0
        assert scores[("SY", datetime(2020, 2, 1, tzinfo=UTC))] == 0.5
        assert scores[("SY", datetime(2020, 3, 1, tzinfo=UTC))] == pytest.approx(2 / 3)

    def test_strictly_past_only(self) -> None:
        # Changing a FUTURE label must not change the score at an earlier month.
        flipped = [dict(c) for c in PANEL]
        flipped[2]["label_any"] = 0  # SY March
        base = score_base_rate(PANEL)
        alt = score_base_rate(flipped)
        key_feb = ("SY", datetime(2020, 2, 1, tzinfo=UTC))
        assert base[key_feb] == alt[key_feb]

    def test_first_country_month_uses_own_label_only(self) -> None:
        # Expanding mean over months <= t is never empty (includes current),
        # so the first US month is just its own label.
        scores = score_base_rate(PANEL)
        assert scores[("US", datetime(2020, 1, 1, tzinfo=UTC))] == 0.0


class TestComposite:
    def test_score_is_panel_composite_value(self) -> None:
        panel = [
            {**_cell("SY", 2020, 1, 0), "composite_score": 0.8},
            {**_cell("SY", 2020, 2, 1), "composite_score": None},
        ]
        scores = score_composite(panel)
        assert scores == {("SY", datetime(2020, 1, 1, tzinfo=UTC)): 0.8}

    def test_nan_composite_skipped(self) -> None:
        import math

        panel = [{**_cell("SY", 2020, 1, 0), "composite_score": math.nan}]
        assert score_composite(panel) == {}
