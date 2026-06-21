"""Tests for `app.enrichment.city.city_for`."""

from __future__ import annotations

import pytest

from app.enrichment.city import city_for


@pytest.mark.parametrize(
    "text,expected_iso,expected_name_contains",
    [
        ("Edinburgh knife attack reported", "GB", "edinburgh"),
        ("Karachi blast wounds five", "PK", "karachi"),
        ("Mumbai stock market closes higher", "IN", "mumbai"),
        ("Heavy rain in Lahore overnight", "PK", "lahore"),
        ("Tokyo exchange opens flat", "JP", "tokyo"),
        ("Berlin court sentences former minister", "DE", "berlin"),
        ("Lagos floods displace thousands", "NG", "lagos"),
    ],
)
def test_known_cities(text: str, expected_iso: str, expected_name_contains: str) -> None:
    hit = city_for(text)
    assert hit is not None
    assert hit.iso == expected_iso
    assert expected_name_contains in hit.name.lower()


def test_country_hint_disambiguates_collision() -> None:
    # Hyderabad exists in both IN and PK. Default (by population) lands in
    # IN; with a PK hint it should land in Pakistan.
    hit_default = city_for("Hyderabad police arrest two")
    assert hit_default is not None
    assert hit_default.iso == "IN"

    hit_pk = city_for("Hyderabad police arrest two", country_hint="PK")
    assert hit_pk is not None
    assert hit_pk.iso == "PK"


def test_returns_none_for_no_match() -> None:
    assert city_for("a generic morning of nothing in particular") is None


def test_empty_string_returns_none() -> None:
    assert city_for("") is None
    assert city_for("   ") is None


def test_punctuation_does_not_break_match() -> None:
    hit = city_for("Lahore: blast wounds two passers-by")
    assert hit is not None
    assert hit.iso == "PK"
