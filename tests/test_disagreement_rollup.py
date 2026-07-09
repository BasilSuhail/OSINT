"""Tests for the (country-pair, month) roll-up — WS-B step 3 (#372)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.disagreement.rollup import aggregate_pairs


def _row(month: str, pairs: dict[str, float]) -> dict:
    return {
        "first_seen": datetime.fromisoformat(f"{month}-15T12:00:00+00:00"),
        "components": {"pairs": pairs},
    }


def test_aggregates_mean_per_pair_month() -> None:
    got = aggregate_pairs(
        [
            _row("2026-07", {"GB|RU": 0.8, "GB|US": 0.2}),
            _row("2026-07", {"GB|RU": 0.6}),
            _row("2026-06", {"GB|RU": 0.4}),
        ]
    )
    assert got[("GB", "RU", "2026-07-01")] == {"n_stories": 2, "mean_divergence": 0.7}
    assert got[("GB", "US", "2026-07-01")] == {"n_stories": 1, "mean_divergence": 0.2}
    assert got[("GB", "RU", "2026-06-01")] == {"n_stories": 1, "mean_divergence": 0.4}


def test_rows_without_pairs_component_excluded() -> None:
    legacy = {"first_seen": datetime(2026, 7, 1, tzinfo=UTC), "components": {"groups": {}}}
    assert aggregate_pairs([legacy]) == {}
