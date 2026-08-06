"""A place name in a sentence that is not a place (#800).

The rule decides whether "Edinburgh" is the capital of Scotland or a man's
title. Wrong in one direction it floods a city search with royal gossip;
wrong in the other it silently deletes real news about the city. Both
failures are invisible without a test that names them.
"""

from __future__ import annotations

import pytest

from app.enrichment.name_collision import is_collision


class TestTitlesAreNotPlaces:
    @pytest.mark.parametrize(
        "text",
        [
            "The Duke of Edinburgh calls on Britain to fly the Red Ensign",
            "The Duke and Duchess of Edinburgh's courtside reactions go viral",
            "The Duchess of Edinburgh cheers Wales' biggest rural celebration",
            "Tributes to teenager who died during Duke of Edinburgh expedition",
            "Hundreds collect their Edinburgh Award at a ceremony in Cardiff",
        ],
    )
    def test_caught(self, text: str) -> None:
        assert is_collision(text, "edinburgh")

    def test_other_titles_and_places(self) -> None:
        assert is_collision("The Prince of Wales visits a factory", "wales")
        assert is_collision("The Bishop of Durham speaks in the Lords", "durham")


class TestPlacesSurvive:
    @pytest.mark.parametrize(
        "text",
        [
            "Historic building wrecked in major blaze on Edinburgh's Princes Street",
            "Edinburgh's tourist tax has now launched",
            "Two pedestrians critical after crash outside Edinburgh hospital",
            "King's Theatre in Edinburgh re-opens after £41m refurbishment",
            "Police make 49 arrests in first month of Edinburgh city centre crackdown",
        ],
    )
    def test_kept(self, text: str) -> None:
        assert not is_collision(text, "edinburgh")

    def test_a_single_real_mention_rescues_the_row(self) -> None:
        """The rule is *every* mention, not *any*. A story carrying both is
        about the place, and dropping it would trade one wrong answer for
        another — #717's precision failure, in reverse."""
        text = "The Duke of Edinburgh opened the new bridge in Edinburgh this morning"
        assert not is_collision(text, "edinburgh")

    def test_a_city_that_is_nobody_s_title(self) -> None:
        assert not is_collision("Firefighters tackle a large blaze in Lahore", "lahore")


class TestDegenerateInput:
    def test_absent_term(self) -> None:
        assert not is_collision("Flooding closes roads across Fife", "edinburgh")

    def test_empty(self) -> None:
        assert not is_collision("", "edinburgh")
        assert not is_collision("The Duke of Edinburgh", "")

    def test_substring_is_not_a_mention(self) -> None:
        """Word boundaries: "Fife" must not match inside "Fifeshire"."""
        assert not is_collision("Fifeshire council meets", "fife")
