"""Tests for scripts/backfill_news_geo.py (#717)."""

from __future__ import annotations

from app.enrichment.geo import resolved_news_scope
from scripts.backfill_news_geo import resolve_row


def test_resolves_from_stored_payload() -> None:
    payload = {
        "title": "Drought declared across whole of Wales",
        "summary": "Conditions deteriorate.",
    }
    verdict = resolve_row(payload, default_country="GB", desk_country="GB")
    assert verdict.iso == "GB"
    assert verdict.basis == "term"


def test_desk_country_applies_to_a_placeless_stored_row() -> None:
    payload = {"title": "The Papers: 'Future looking droughtful'", "summary": ""}
    assert resolve_row(payload, default_country="GB", desk_country="GB").iso == "GB"
    assert resolve_row(payload, default_country="GB", desk_country=None).iso is None


def test_missing_payload_fields_are_safe() -> None:
    assert resolve_row({}, default_country=None, desk_country=None).iso is None
    assert resolve_row({"title": None}, default_country=None, desk_country=None).iso is None


def test_ambiguous_row_is_cleared_not_kept() -> None:
    # A row previously tagged GB because it said "London" must come back
    # with no country, not keep its stale value.
    payload = {
        "title": "France, Spain and Greece battle wildfires",
        "summary": "Reported from London.",
    }
    verdict = resolve_row(payload, default_country=None, desk_country=None)
    assert verdict.iso is None


def test_countried_coordless_row_is_not_local() -> None:
    """A resolved country with no coordinates must not be re-tagged "local".

    Before #717, "local" was only reachable through a matched city, which
    always carried coordinates. The term layer can now name a country
    with no city at all — such a row must land in "world", or MapPane
    falls back to the country centroid, stacking rows from every feed
    onto one point (the #166 blob, #717 whole-branch review Critical 1).
    """
    payload = {
        "title": "Can the West really decouple from China?",
        "summary": "Written from London.",
    }
    verdict = resolve_row(payload, default_country="CN", desk_country=None)
    assert verdict.iso == "CN"
    assert verdict.lat is None
    assert verdict.lon is None
    assert (
        resolved_news_scope(verdict.iso, verdict.lat, verdict.lon, default_country="CN") == "world"
    )
