"""Tests for `app.ranking.rank` — univariate indicator value ranking (WS-F, #376)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.ranking.rank import rank_indicators

T0 = datetime(2020, 1, 1, tzinfo=UTC)


def _month(i: int) -> datetime:
    return datetime(2020 + (i // 12), (i % 12) + 1, 1, tzinfo=UTC)


def _panel(rows: list[tuple[str, int, int, dict]]) -> list[dict]:
    return [
        {"country": country, "month": _month(i), "label_any": label, **signals}
        for country, i, label, signals in rows
    ]


def test_perfect_indicator_ranks_first_with_auroc_one() -> None:
    # good tracks next-month labels exactly; noise is constant (no signal).
    rows = []
    for i in range(12):
        label = 1 if i % 3 == 0 else 0
        next_label = 1 if (i + 1) % 3 == 0 else 0
        rows.append(("AA", i, label, {"good": float(next_label), "noise": 0.5}))
    ranked = rank_indicators(
        _panel(rows),
        indicators=("good", "noise"),
        horizons=(1,),
        eval_start=_month(0),
        eval_end=_month(11),
    )
    by_name = {(r["indicator"], r["variant"]): r for r in ranked}
    assert by_name[("good", "raw")]["auroc"] == 1.0
    assert by_name[("noise", "raw")]["auroc"] is None or by_name[("noise", "raw")]["auroc"] == 0.5
    # Ranking within a horizon is AUROC-descending; the perfect signal leads.
    horizon_rows = [r for r in ranked if r["horizon_months"] == 1]
    assert horizon_rows[0]["indicator"] == "good"


def test_abs_variant_catches_two_sided_signal() -> None:
    # two_sided swings negative before events — raw AUROC poor, |value| strong.
    rows = []
    for i in range(12):
        next_label = 1 if (i + 1) % 3 == 0 else 0
        value = -2.0 if next_label else 0.1
        rows.append(("AA", i, 1 if i % 3 == 0 else 0, {"two_sided": value}))
    ranked = rank_indicators(
        _panel(rows),
        indicators=("two_sided",),
        horizons=(1,),
        eval_start=_month(0),
        eval_end=_month(11),
    )
    by_variant = {r["variant"]: r for r in ranked}
    assert by_variant["abs"]["auroc"] == 1.0
    assert by_variant["raw"]["auroc"] == 0.0


def test_null_indicator_rows_excluded_from_its_support() -> None:
    rows = []
    for i in range(12):
        signals = {"patchy": float(i % 2) if i < 6 else None}
        rows.append(("AA", i, i % 2, signals))
    ranked = rank_indicators(
        _panel(rows),
        indicators=("patchy",),
        horizons=(1,),
        eval_start=_month(0),
        eval_end=_month(11),
    )
    (raw,) = [r for r in ranked if r["variant"] == "raw"]
    assert raw["n"] <= 6  # null months cannot enter the support


def test_eval_window_respected() -> None:
    rows = [("AA", i, i % 2, {"sig": 0.5}) for i in range(12)]
    ranked = rank_indicators(
        _panel(rows),
        indicators=("sig",),
        horizons=(1,),
        eval_start=_month(3),
        eval_end=_month(5),
    )
    (raw,) = [r for r in ranked if r["variant"] == "raw"]
    assert raw["n"] == 3
