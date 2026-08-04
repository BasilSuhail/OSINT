"""Search: places navigate, words retrieve (#779)."""

from __future__ import annotations

from app.search import MIN_QUERY_LEN, find_places


class TestPlaceLookup:
    def test_a_plain_city_resolves_to_one_place(self) -> None:
        hits = find_places("Lahore")
        assert len(hits) == 1
        assert hits[0].country == "PK"
        assert hits[0].kind == "city"

    def test_a_region_resolves_too(self) -> None:
        hits = find_places("Kerala")
        assert hits and hits[0].country == "IN"
        assert hits[0].kind == "region"

    def test_same_name_in_one_country_stays_several_places(self) -> None:
        # Five Springfields in the United States, and they are five different
        # towns. Folding them into one answers an ambiguous query with a
        # single confident wrong result.
        hits = find_places("Springfield")
        assert len(hits) >= 4
        points = {(round(h.lat, 3), round(h.lon, 3)) for h in hits}
        assert len(points) == len(hits), "distinct places collapsed"

    def test_contested_names_are_captioned_by_region(self) -> None:
        # The caption has to be the thing that differs: "United States"
        # five times over tells the reader nothing.
        contexts = [h.context for h in find_places("Springfield")]
        assert len({c for c in contexts}) > 1
        assert any("," in c for c in contexts)

    def test_a_name_separated_by_country_is_not_captioned_by_region(self) -> None:
        # London appears in three countries and the country alone separates
        # them. Reaching for a region produced "London — Wales", because
        # England was removed as a region in #725 for being country-sized.
        london = [h for h in find_places("London") if h.name.lower() == "london"]
        assert len(london) >= 2
        gb = next(h for h in london if h.country == "GB")
        assert "wales" not in gb.context.lower()

    def test_bigger_places_come_first(self) -> None:
        hits = [h for h in find_places("London") if h.name.lower() == "london"]
        assert hits[0].country == "GB"

    def test_prefix_matches_are_offered(self) -> None:
        assert any(h.name.lower().startswith("lond") for h in find_places("Londo"))

    def test_a_single_character_is_a_keystroke_not_a_question(self) -> None:
        assert find_places("L") == []
        assert MIN_QUERY_LEN == 2

    def test_an_unknown_word_finds_no_place(self) -> None:
        # And must not guess: falling through to content search is the
        # correct answer for a word that names nowhere.
        assert find_places("ceasefire") == []
        assert find_places("qwertyuiop") == []
