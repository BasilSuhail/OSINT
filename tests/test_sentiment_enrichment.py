"""Tests for ``app.enrichment.sentiment.score_text``."""

from __future__ import annotations

import pytest

from app.enrichment.sentiment import (
    SENTIMENT_METHOD_VERSION,
    SentimentHit,
    score_text,
)


def test_method_version_constant() -> None:
    assert SENTIMENT_METHOD_VERSION == "vader.v1.0"


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_inputs_return_none(text: str | None) -> None:
    assert score_text(text or "") is None


def test_negative_headline_returns_negative_compound() -> None:
    hit = score_text("Stocks crash, traders panic, market fears spread")
    assert hit is not None
    assert hit.compound < -0.3
    assert hit.label == "negative"


def test_positive_headline_returns_positive_compound() -> None:
    hit = score_text("Wonderful breakthrough excites researchers, brilliant success and joy")
    assert hit is not None
    assert hit.compound > 0.3
    assert hit.label == "positive"


def test_neutral_headline_returns_neutral_label() -> None:
    hit = score_text("Government publishes quarterly economic data tables")
    assert hit is not None
    assert hit.label == "neutral"


def test_hit_carries_method_version() -> None:
    hit = score_text("Police investigate routine matter")
    assert hit is not None
    assert hit.method_version == SENTIMENT_METHOD_VERSION


def test_compound_clamped_to_unit_interval() -> None:
    """Even on an extreme input VADER stays within [-1, 1] by design."""
    hit = score_text("KILL MURDER ATTACK BOMB BLOOD WAR DEATH DESTROY")
    assert hit is not None
    assert -1.0 <= hit.compound <= 1.0


def test_lru_cache_returns_identical_hits_for_same_text() -> None:
    """Round-trip the cache once to confirm it stays a hit on second call."""
    text = "Quiet news on a calm afternoon"
    first = score_text(text)
    second = score_text(text)
    assert first == second
    assert isinstance(first, SentimentHit)
