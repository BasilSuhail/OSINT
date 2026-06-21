"""Pure tests for ``app.cii.scoring``.

Orchestrator + DB I/O are exercised separately so this file stays a
unit test of the formula.
"""

from __future__ import annotations

import math

from app.cii.config import DEFAULT_CII_BASELINE, CiiBaseline, baseline_for
from app.cii.scoring import CII_METHOD_VERSION, CiiInputs, compute_cii


def test_method_version_constant() -> None:
    assert CII_METHOD_VERSION == "cii.v1.0"


def test_zero_inputs_returns_pure_baseline_contribution() -> None:
    """No events → CII total reduces to 0.40 x baseline / 100."""
    cfg = CiiBaseline(baseline=20.0, multiplier=1.0)
    out = compute_cii("GB", CiiInputs(), baseline=cfg)
    assert out.unrest == 0.0
    assert out.conflict == 0.0
    assert out.security == 0.0
    assert out.information == 0.0
    assert out.event_score == 0.0
    assert math.isclose(out.total, 0.40 * 20.0 / 100.0, abs_tol=1e-9)


def test_total_stays_in_unit_interval_even_for_saturated_inputs() -> None:
    """Huge inputs across every component should clamp to ≤ 1.0."""
    cfg = CiiBaseline(baseline=50.0, multiplier=1.5)
    out = compute_cii(
        "PK",
        CiiInputs(
            unrest_signals=10_000,
            unrest_fatalities=1000,
            conflict_events=5_000,
            quake_m5_plus=50,
            hazard_orange_red=50,
            news_volume=10_000,
        ),
        baseline=cfg,
    )
    assert 0.0 <= out.total <= 1.0
    # Every sub-score is capped at 100.
    for v in (out.unrest, out.conflict, out.security, out.information):
        assert 0.0 <= v <= 100.0


def test_multiplier_amplifies_event_score() -> None:
    """Same raw inputs, two different multipliers — higher multiplier → higher score."""
    inputs = CiiInputs(
        unrest_signals=20,
        conflict_events=40,
        quake_m5_plus=2,
        hazard_orange_red=1,
        news_volume=120,
    )
    low = compute_cii("XX", inputs, baseline=CiiBaseline(baseline=10.0, multiplier=0.6))
    high = compute_cii("YY", inputs, baseline=CiiBaseline(baseline=10.0, multiplier=1.4))
    assert high.total > low.total
    assert high.event_score > low.event_score


def test_baseline_default_lookup_falls_back_to_default() -> None:
    assert baseline_for(None) == DEFAULT_CII_BASELINE
    assert baseline_for("ZZ") == DEFAULT_CII_BASELINE


def test_baseline_known_country_returns_table_value() -> None:
    cfg = baseline_for("PK")
    assert cfg.baseline > DEFAULT_CII_BASELINE.baseline
    assert cfg.multiplier > 1.0


def test_components_payload_round_trip() -> None:
    """as_payload() produces a dict whose floats survive a JSON pass."""
    import json

    out = compute_cii("UA", CiiInputs(conflict_events=120, news_volume=80))
    payload = out.as_payload()
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    assert decoded["method_version"] == CII_METHOD_VERSION
    assert 0.0 <= decoded["total"] <= 1.0
