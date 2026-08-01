"""Tests for `app.enrichment.geo.resolve_geo` (#717).

Cases are drawn from real headlines measured on the live database on
2026-07-30 and quoted in the issue.
"""

from __future__ import annotations

import pytest

from app.enrichment.geo import resolve_geo

# --- Recall: the 73% that used to get nothing ---------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Drought declared across whole of Wales as conditions deteriorate", "GB"),
        ("UK firefighters battling blaze close to Sizewell B nuclear plant", "GB"),
        ("Indonesia seeks balance between AI tech and creators in Copyright Bill", "ID"),
        ("Spain's Cucurella keeps World Cup vow with De la Fuente tattoo", "ES"),
        ("Russia to insist on identifying masterminds of Nord Stream sabotage", "RU"),
        ("German police raid three properties in Bavaria", "DE"),
        ("A man died in Britain yesterday, police say", "GB"),
    ],
)
def test_single_country_in_title_resolves(title: str, expected: str) -> None:
    verdict = resolve_geo(title)
    assert verdict.iso == expected
    # "term" or "region" — a story naming a region (Wales, Bavaria) resolves
    # the same country and additionally earns a point, which reads as
    # "region". The country is what this test is about.
    assert verdict.basis in {"term", "region"}


# --- Precision: the 12-of-19 wrong GB rows ------------------------------


def test_city_mention_does_not_beat_the_subject_country() -> None:
    # Real row: tagged GB because it said "London". It is about China.
    verdict = resolve_geo("Can the West really decouple from China?")
    assert verdict.iso == "CN"
    assert verdict.basis == "term"


def test_coordinates_are_dropped_when_the_city_is_in_another_country() -> None:
    # Real row: pinned on London, about a Russian missile strike in Ukraine.
    verdict = resolve_geo("Russia likely used N.Korean missile in deadly Ukraine strike")
    assert verdict.iso in {"RU", "UA", None}
    assert verdict.lat is None
    assert verdict.lon is None


def test_lead_position_breaks_a_two_country_headline() -> None:
    verdict = resolve_geo("Israel slams Canada for statement opposing settlement expansion")
    assert verdict.iso == "IL"
    assert verdict.basis == "term"


def test_ambiguous_headline_resolves_to_nothing() -> None:
    verdict = resolve_geo("France, Spain and Greece battle wildfires that forced evacuations")
    assert verdict.iso is None
    assert verdict.basis == "ambiguous"


def test_ambiguous_headline_does_not_fall_through_to_city() -> None:
    # Names three countries and a city. The city must not decide it.
    verdict = resolve_geo(
        "As Iran and Ukraine wars converge, Israel and Ukraine may come together",
        "Analysts in Paris disagree.",
    )
    assert verdict.basis == "ambiguous"
    assert verdict.iso is None


# --- Genuinely placeless stories stay placeless -------------------------


@pytest.mark.parametrize(
    "title",
    [
        "'Spider-Man: Brand New Day' makes historical debut at box office",
        "Gold prices rise in local, global markets",
        "1967 warning on tropical mountains trapping species confirmed by beetle study",
    ],
)
def test_placeless_story_has_no_country(title: str) -> None:
    verdict = resolve_geo(title)
    assert verdict.iso is None
    assert verdict.basis == "none"


# --- Layer order --------------------------------------------------------


def test_city_layer_used_only_when_no_country_term_scored() -> None:
    verdict = resolve_geo("Karachi blast wounds five")
    assert verdict.iso == "PK"
    assert verdict.basis == "city"
    assert verdict.city == "Karachi"
    assert verdict.lat is not None
    assert verdict.lon is not None


def test_city_supplies_coordinates_when_it_agrees_with_the_term_winner() -> None:
    verdict = resolve_geo("British police close Manchester road after crash")
    assert verdict.iso == "GB"
    assert verdict.basis == "term"
    assert verdict.city == "Manchester"
    assert verdict.lat is not None


def test_desk_country_is_the_last_resort_only() -> None:
    placeless = "Gold prices rise in local, global markets"
    assert resolve_geo(placeless).iso is None
    assert resolve_geo(placeless, desk_country="PK").iso == "PK"
    assert resolve_geo(placeless, desk_country="PK").basis == "desk"


def test_desk_country_never_overrides_a_text_signal() -> None:
    verdict = resolve_geo("Ukrainian drone attacks reported overnight", desk_country="GB")
    assert verdict.iso == "UA"
    assert verdict.basis == "term"


def test_desk_country_does_not_rescue_an_ambiguous_story() -> None:
    verdict = resolve_geo("France, Spain and Greece battle wildfires", desk_country="GB")
    assert verdict.iso is None
    assert verdict.basis == "ambiguous"


# --- Field weighting ----------------------------------------------------


def test_title_outweighs_summary() -> None:
    verdict = resolve_geo(
        "Japan turns to imported crude as Asia feels supply pinch",
        "Traders in Canada, Canada and Canada commented.",
    )
    # JP: 3.0 in the title + 1.0 lead bonus = 4.0.
    # CA: 1.0 in the summary — repeating it three times scores once, not
    # three times, so a summary can never shout down a headline.
    assert verdict.iso == "JP"


def test_empty_input_is_safe() -> None:
    verdict = resolve_geo("")
    assert verdict.iso is None
    assert verdict.basis == "none"
    assert verdict.lat is None


def test_resolution_is_deterministic() -> None:
    title = "Israel slams Canada for statement opposing settlement expansion"
    assert {resolve_geo(title).iso for _ in range(5)} == {"IL"}


# --- Lead bonus: anchored at offset 0, withheld for a coordinated list --


def test_coordinated_leading_countries_get_no_bonus() -> None:
    verdict = resolve_geo("France, Spain and Greece battle wildfires")
    assert verdict.iso is None
    assert verdict.basis == "ambiguous"


def test_leading_country_followed_by_a_verb_keeps_the_bonus() -> None:
    verdict = resolve_geo("Iraq demands evidence that attacks on Saudi Arabia originated abroad")
    assert verdict.iso == "IQ"
    assert verdict.basis == "term"


def test_country_not_anchored_at_the_start_gets_no_bonus() -> None:
    # "Japan" sits at word 2, not word 0. If the bonus leaked to a country
    # merely appearing early rather than one anchored at the very start,
    # this would resolve JP; anchored correctly, it ties 3.0/3.0 and the
    # story is ambiguous.
    verdict = resolve_geo("Toyota Japan plant supplies cars to Germany")
    assert verdict.iso is None


def test_multi_word_country_can_lead() -> None:
    assert resolve_geo("South Korea slams Japan over island dispute").iso == "KR"
    assert resolve_geo("New Zealand slams Australia over trade deal").iso == "NZ"


def test_country_not_at_the_start_does_not_lead() -> None:
    # "iran" begins at offset 3, not 0 — nothing leads, so the tie stands.
    verdict = resolve_geo("As Iran and Ukraine wars converge, Israel and Ukraine may come together")
    assert verdict.iso is None
    assert verdict.basis == "ambiguous"


# --- Coordination suppression must span multi-word country names -------
#
# Bug: `_opens_with_coordinated_countries` used to walk single whitespace
# tokens ("South", "Korea", ...) while `leading_iso` anchored whole,
# possibly multi-word names via `country_at`. A headline opening with a
# two-word country in a coordinated list ("South Korea, Japan and
# China") never had its lead bonus suppressed — "South" alone matched no
# country, the walk gave up immediately, and the story resolved to
# whichever multi-word country happened to sit first instead of being
# ambiguous.


@pytest.mark.parametrize(
    "title",
    [
        "United States and China agree tariff truce",
        "South Korea, Japan and China agree to talks",
        "New Zealand and Australia sign defence pact",
    ],
)
def test_coordinated_multiword_countries_get_no_lead_bonus(title: str) -> None:
    verdict = resolve_geo(title)
    assert verdict.iso is None
    assert verdict.basis == "ambiguous"


def test_as_well_as_coordinated_countries_get_no_lead_bonus() -> None:
    # Kept separate from the multi-word test above: this pins the
    # "as well as" phrase specifically, so a regression in phrase
    # handling reads differently from one in multi-word matching.
    verdict = resolve_geo("Britain as well as France announce new sanctions")
    assert verdict.iso is None
    assert verdict.basis == "ambiguous"


# Single-subject headlines opening with a (possibly multi-word) country
# must still resolve — a future "fix" that suppresses the lead bonus too
# broadly, and makes everything ambiguous, must not be able to call this
# green. "Israel slams Canada..." and "South Korea slams Japan..." above
# already cover this; this one adds the remaining case from the issue.


def test_multiword_leading_country_followed_by_a_verb_keeps_the_bonus() -> None:
    verdict = resolve_geo("Iraq demands evidence that attacks on Saudi Arabia originated abroad")
    assert verdict.iso == "IQ"
    assert verdict.basis == "term"


# --- A lone sub-margin candidate must not block the city/desk layers ----
#
# Bug: a single candidate that failed to clear MARGIN was labelled
# "ambiguous" and returned immediately, before the city and desk layers
# ever ran — even though there was no runner-up to be ambiguous *against*.
# That meant adding evidence to a story could only ever make its answer
# worse, never better.


def test_lone_weak_region_in_summary_does_not_block_the_city_layer() -> None:
    # The pair below is the point: the bare title resolves via the city
    # layer to PK/Karachi. Adding "Sindh" (a PK region, summary-weighted
    # at 0.5 with no runner-up) used to be treated the same as a genuine
    # multi-country tie, taking the "ambiguous" branch and never reaching
    # the city layer at all — so the *better-evidenced* version regressed
    # to no answer instead of the same PK/Karachi verdict.
    bare = resolve_geo("Karachi blast wounds five", "")
    with_weak_summary = resolve_geo("Karachi blast wounds five", "Reported from a Sindh hospital.")

    assert bare.iso == "PK"
    assert bare.basis == "city"

    assert with_weak_summary.iso == "PK"
    assert with_weak_summary.basis == "city"


def test_multi_candidate_tie_still_blocks_the_city_layer() -> None:
    # Pins the other side of the fix above: a genuine multi-country tie
    # (not a lone sub-margin candidate) must still be "ambiguous" and
    # must NOT fall through to the city layer, even when the text names
    # a real gazetteer city. London is in the gazetteer; it must not
    # rescue this story.
    verdict = resolve_geo("France, Spain and Greece battle wildfires", "Reported from London.")
    assert verdict.iso is None
    assert verdict.basis == "ambiguous"


# --- Region coordinates (#717) -----------------------------------------


def test_region_supplies_a_point_when_no_city_does() -> None:
    verdict = resolve_geo("Drought declared across whole of Wales")
    assert verdict.iso == "GB"
    assert verdict.basis == "region"
    # Mid-Wales, not the UK centroid and not London.
    assert verdict.lat is not None and verdict.lon is not None
    assert 51.0 < verdict.lat < 53.5
    assert -5.0 < verdict.lon < -2.5


def test_two_regions_of_one_country_pin_in_different_places() -> None:
    kerala = resolve_geo("Kerala HC directs State to operationalise NDPS Courts")
    karnataka = resolve_geo("Karnataka govt. sets up panel for recruitment reforms")
    assert kerala.iso == karnataka.iso == "IN"
    assert (kerala.lat, kerala.lon) != (karnataka.lat, karnataka.lon)


def test_a_city_still_beats_its_region() -> None:
    # The city gazetteer is more precise; a region is the fallback.
    verdict = resolve_geo("Karachi blast wounds five")
    assert verdict.basis == "city"
    assert verdict.city == "Karachi"


def test_country_without_a_region_keeps_no_point() -> None:
    # "Britain" names no region, so there is nothing finer to pin on.
    verdict = resolve_geo("A man died in Britain yesterday")
    assert verdict.iso == "GB"
    assert verdict.basis == "term"
    assert verdict.lat is None


def test_region_point_never_overrides_an_agreeing_city() -> None:
    verdict = resolve_geo("Bavaria police close Munich road after crash")
    assert verdict.iso == "DE"
    assert verdict.basis == "term"
    assert verdict.city == "Munich"


def test_ambiguous_story_gets_no_region_point() -> None:
    verdict = resolve_geo("Wales, Scotland and Bavaria all report drought")
    assert verdict.lat is None


def test_england_names_the_country_but_claims_no_place() -> None:
    # England is ~84% of the UK, so an England pin is a UK pin — the blob
    # #719 removed. It stays valid country evidence and carries no point
    # (#725).
    verdict = resolve_geo("Ambulance delays worsen across England")
    assert verdict.iso == "GB"
    assert verdict.lat is None and verdict.lon is None


def test_the_other_uk_nations_keep_their_points() -> None:
    for title, iso in [
        ("Drought declared across whole of Wales", "GB"),
        ("Scotland reports record NHS waiting times", "GB"),
        ("Northern Ireland assembly returns after recess", "GB"),
    ]:
        verdict = resolve_geo(title)
        assert verdict.iso == iso, title
        assert verdict.lat is not None, f"{title} should still pin"


def test_a_placeable_nation_wins_over_england() -> None:
    verdict = resolve_geo("England and Wales see drought spread")
    assert verdict.iso == "GB"
    # Wales is the one that knows where it is.
    assert verdict.lat is not None


# --- Territories that are places, not countries (#737) ------------------


def test_a_palestinian_territory_carries_a_point() -> None:
    verdict = resolve_geo("Palestinian children detained in West Bank raids")
    assert verdict.iso == "PS"
    assert verdict.lat is not None and verdict.lon is not None
    # The West Bank, not the middle of a country.
    assert 31.3 < verdict.lat < 32.6
    assert 34.9 < verdict.lon < 35.6


def test_gaza_and_the_west_bank_are_different_places() -> None:
    gaza = resolve_geo("Palestinian families flee northern Gaza")
    west_bank = resolve_geo("Palestinian villagers blocked in the West Bank")
    assert gaza.lat is not None and west_bank.lat is not None
    assert (gaza.lat, gaza.lon) != (west_bank.lat, west_bank.lon)


def test_a_territory_point_never_becomes_a_country_pin() -> None:
    # The England rule (#725): naming a whole country is not knowing where.
    for title in [
        "Israel says it killed three Hezbollah fighters",
        "Ambulance delays across England",
    ]:
        assert resolve_geo(title).lat is None, title


def test_a_passing_mention_of_a_territory_does_not_move_the_pin() -> None:
    # China is the subject; Gaza is scenery. Pinning this in Gaza would be
    # the "mentioned vs about" error the margin exists to prevent.
    verdict = resolve_geo("China unveils new trade policy as Gaza ceasefire holds elsewhere")
    assert verdict.iso == "CN"
    assert verdict.lat is None
