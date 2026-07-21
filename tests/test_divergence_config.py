"""Tests for ``app.divergence.config`` source-side classification and constants."""

from __future__ import annotations

from app.divergence.config import classify_side


def test_physical_sources_classified() -> None:
    assert classify_side("usgs-quake") == "physical"
    assert classify_side("gdacs") == "physical"
    assert classify_side("viirs-flaring") == "physical"
    assert classify_side("aisstream") == "physical"


def test_intensity_blind_sources_are_excluded(fixture_free=None) -> None:
    # nasa-firms carries no severity and no magnitude, so it scored 0.0 on a
    # scale where 0.0 is indistinguishable from "nothing happened" (#497).
    assert classify_side("nasa-firms") is None
    assert classify_side("opensky-adsb") is None


def test_narrative_sources_classified() -> None:
    assert classify_side("gdelt") == "narrative"
    assert classify_side("rss-bbc-world") == "narrative"


def test_ignored_sources_return_none() -> None:
    assert classify_side("yfinance") is None
    assert classify_side("abuse-ch-feodo") is None
    assert classify_side("uk-police") is None
