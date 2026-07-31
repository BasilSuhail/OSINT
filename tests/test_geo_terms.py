"""Tests for the geo term index (#717)."""

from __future__ import annotations

import pytest

from app.enrichment.geo_terms import find_isos, term_index


def test_country_names_come_from_natural_earth() -> None:
    # Not listed in geo_terms.json — must be inherited from admin0.
    assert "IN" in find_isos("Reports from India this morning")
    assert "JP" in find_isos("A quiet week in Japan")


def test_demonym_matches() -> None:
    assert "DE" in find_isos("German police raided the building")
    assert "GB" in find_isos("British troops withdraw")
    assert "UA" in find_isos("Ukrainian drone attacks reported")


def test_colloquial_alias_matches() -> None:
    assert "GB" in find_isos("A man died in Britain yesterday")


def test_subnational_region_matches() -> None:
    assert "GB" in find_isos("Drought declared across whole of Wales")
    assert "DE" in find_isos("Bavaria tightens rules")
    assert "IN" in find_isos("Tamil Nadu government must create land banks")
    assert "US" in find_isos("Trump touts tariffs while in Michigan")


def test_region_is_reported_as_region_class() -> None:
    assert find_isos("Drought declared across whole of Wales")["GB"] == {"region"}
    assert find_isos("A man died in Britain yesterday")["GB"] == {"name"}


def test_abbreviations_are_case_sensitive() -> None:
    # The pronoun trap: this headline must NOT resolve to the United States.
    assert "US" not in find_isos(
        "On a record-breaking night, Australian swimming finds a way to surprise us"
    )
    assert "US" in find_isos("US launches another wave of strikes")
    assert "GB" in find_isos("UK firefighters battling blaze near Sizewell B")


def test_no_substring_bleed() -> None:
    # "Oman" inside "Romania", "Chad" inside "Chadwick", "Mali" inside "Somalia".
    assert "OM" not in find_isos("Romania holds elections")
    assert "TD" not in find_isos("Chadwick Boseman remembered")
    assert "ML" not in find_isos("Somalia reports flooding")


def test_punctuation_does_not_break_match() -> None:
    assert "ES" in find_isos("Spain's Cucurella keeps World Cup vow")


def test_longer_region_consumes_shorter_overlapping_one() -> None:
    # "New South Wales" (AU) must not leak a false "Wales" (GB) match.
    result = find_isos("Flooding hits New South Wales again")
    assert "GB" not in result
    assert "AU" in result


def test_punctuated_abbreviations_match() -> None:
    assert "GB" in find_isos("U.K. firefighters battle blaze")
    assert "US" in find_isos("U.S. forces deployed overseas")


def test_hyphenated_country_name_matches_correctly() -> None:
    result = find_isos("Guinea-Bissau holds elections")
    assert "GW" in result
    assert "GN" not in result


def test_empty_text_returns_empty() -> None:
    assert find_isos("") == {}
    assert find_isos("   ") == {}


def test_result_is_safe_to_mutate() -> None:
    # find_isos is lru_cache'd; a caller mutating the returned dict must
    # not corrupt what a later call with the same text returns.
    text = "German police raided the building"
    first = find_isos(text)
    first["FAKE"] = frozenset({"name"})
    first.pop("DE", None)
    second = find_isos(text)
    assert "DE" in second
    assert "FAKE" not in second


def test_index_is_sorted_longest_first() -> None:
    lengths = [len(t.text) for t in term_index()]
    assert lengths == sorted(lengths, reverse=True)


def test_index_has_no_short_junk_terms() -> None:
    # Two-letter lowercase terms would match prepositions. Abbreviations are
    # allowed to be short only because they are matched case-sensitively.
    for term in term_index():
        if not term.case_sensitive:
            assert len(term.text) >= 4, f"{term.text!r} is too short to match safely"


@pytest.mark.parametrize("iso", ["GB", "US", "IN", "PK", "RU", "UA", "CN", "IL", "PS", "DE"])
def test_high_volume_countries_have_demonyms(iso: str) -> None:
    classes = {t.term_class for t in term_index() if t.iso == iso}
    assert "name" in classes
