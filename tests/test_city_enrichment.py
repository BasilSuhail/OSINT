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


# --- Expanded gazetteer (#723) -----------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Leeds hospital trust reports failings", "Leeds"),
        ("Bristol harbour festival returns", "Bristol"),
        ("Cambridge students protest at graduation", "Cambridge"),
        ("Spain says migrants are returning from Ceuta", "Ceuta"),
    ],
)
def test_cities_the_old_gazetteer_could_not_reach(text: str, expected: str) -> None:
    hit = city_for(text)
    assert hit is not None
    assert hit.name == expected


@pytest.mark.parametrize(
    "text",
    [
        "Mistaken username sent Man to prison for 18 months",
        "The Hindu brings the historic 1947 Independence Day edition",
        "Reading the report, the committee found no fault",
        "Mobile phone sales fell again this quarter",
    ],
)
def test_common_words_are_not_treated_as_cities(text: str) -> None:
    # Man (CI), Independence (US), Reading (GB), Mobile (US) are all real
    # places whose names are ordinary English. The matcher lowercases, so
    # without the hold-back list these tag whole unrelated stories.
    assert city_for(text) is None


def test_spellings_only_the_previous_gazetteer_had_still_resolve() -> None:
    # The 10m set drops variants the 50m set carried; the build merges
    # them back rather than regressing a match that used to work.
    for text, iso in [
        ("Russia and Ukraine trade fire near Dnipro", "UA"),
        ("Suspect died in Jalandhar road crash", "IN"),
    ]:
        hit = city_for(text)
        assert hit is not None, text
        assert hit.iso == iso


def test_gazetteer_is_substantially_larger_than_before() -> None:
    from app.enrichment.city import _CITIES_RAW

    assert len(_CITIES_RAW) > 7000
    assert sum(1 for c in _CITIES_RAW if c["iso"] == "GB") > 40
