"""The place screen names a country in its first line, so it uses the fine
boundaries — the coarse ones are allowed to be ~10 km wrong and say so."""

from __future__ import annotations

from app.enrichment.boundary import NEAR_BORDER_KM, border_distance_km, precise_country


def test_inland_point_resolves_to_its_country():
    assert precise_country(48.8566, 2.3522) == "FR"


def test_open_ocean_has_no_country():
    assert precise_country(0.0, -140.0) is None


def test_out_of_range_coordinates_are_refused():
    assert precise_country(120.0, 500.0) is None


def test_a_deep_inland_point_is_far_from_any_border():
    distance = border_distance_km(48.8566, 2.3522, "FR")
    assert distance is not None
    assert distance > NEAR_BORDER_KM


def test_a_point_beside_a_border_is_near_it():
    # A few hundred metres inside one side of a well-known land border.
    distance = border_distance_km(47.5586, 7.5886, "CH")
    assert distance is not None
    assert distance < NEAR_BORDER_KM


def test_distance_for_a_country_that_is_not_there_is_none():
    assert border_distance_km(48.8566, 2.3522, "ZZ") is None
