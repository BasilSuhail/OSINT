"""Fetcher registry membership and its lightweight name projection."""

from __future__ import annotations

from app.fetcher_registry import CORE_FETCHER_NAMES, _build_registry, registered_names
from app.sources.rss_registry import feed_enabled_map


def test_registered_names_contains_core_and_enabled_rss_sources() -> None:
    enabled_rss = {source for source, enabled in feed_enabled_map().items() if enabled}

    assert registered_names() >= CORE_FETCHER_NAMES
    assert registered_names() >= enabled_rss


def test_registered_names_excludes_parked_rss_sources() -> None:
    parked_rss = {source for source, enabled in feed_enabled_map().items() if not enabled}

    assert parked_rss
    assert parked_rss.isdisjoint(registered_names())


def test_registered_names_matches_the_shipping_registry() -> None:
    assert registered_names() == frozenset(_build_registry())
