"""Tests for `app.corroboration.score` — the fixed corroboration-v1.0 formula."""

from __future__ import annotations

from app.corroboration.score import SCORE_VERSION, corroboration_score


def test_single_unverified_teller_earns_nothing() -> None:
    score, components = corroboration_score(owner_count=1, confirmed=0, unconfirmed=0)
    assert score == 0.0
    assert components["owner_count"] == 1


def test_each_extra_owner_halves_doubt() -> None:
    assert corroboration_score(owner_count=2, confirmed=0, unconfirmed=0)[0] == 0.5
    assert corroboration_score(owner_count=3, confirmed=0, unconfirmed=0)[0] == 0.75
    assert corroboration_score(owner_count=5, confirmed=0, unconfirmed=0)[0] == 0.9375


def test_sensor_confirmation_halves_doubt_once_more() -> None:
    assert corroboration_score(owner_count=1, confirmed=1, unconfirmed=0)[0] == 0.5
    assert corroboration_score(owner_count=2, confirmed=1, unconfirmed=0)[0] == 0.75
    # Two confirmed claims count once — it is a flag, not a ladder.
    assert corroboration_score(owner_count=2, confirmed=2, unconfirmed=0)[0] == 0.75


def test_unconfirmed_claims_recorded_but_not_penalised() -> None:
    plain = corroboration_score(owner_count=3, confirmed=0, unconfirmed=0)
    claimed = corroboration_score(owner_count=3, confirmed=0, unconfirmed=2)
    assert claimed[0] == plain[0]
    assert claimed[1]["unconfirmed_claims"] == 2


def test_score_bounded_and_versioned() -> None:
    score, components = corroboration_score(owner_count=40, confirmed=1, unconfirmed=0)
    assert 0.0 <= score <= 1.0
    assert components["method_version"] == SCORE_VERSION == "corroboration-v1.0"
