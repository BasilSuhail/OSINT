"""The standing check on the question a reader actually asks (#798).

The detector is the part worth testing. Everything else counts rows; this
decides whether "Edinburgh" in a headline is a place or a man's title, and
getting it wrong in either direction produces a number that lies.
"""

from __future__ import annotations

import pytest

from app.audit.city_probe import CityProbe, format_report, is_collision


class TestIsCollision:
    @pytest.mark.parametrize(
        "text",
        [
            "The Duke of Edinburgh calls on Britain to fly the Red Ensign",
            "The Duke and Duchess of Edinburgh's courtside reactions go viral",
            "Tributes to teenager who died during Duke of Edinburgh expedition",
            "Hundreds receive their Edinburgh Award at a ceremony in Cardiff",
        ],
    )
    def test_a_title_is_not_a_place(self, text: str) -> None:
        assert is_collision(text, "edinburgh")

    @pytest.mark.parametrize(
        "text",
        [
            "Historic building wrecked in major blaze on Edinburgh's Princes Street",
            "Edinburgh's tourist tax has now launched",
            "Two pedestrians in critical condition after crash outside Edinburgh hospital",
            "King's Theatre in Edinburgh re-opens after £41m refurbishment",
        ],
    )
    def test_a_place_is_a_place(self, text: str) -> None:
        assert not is_collision(text, "edinburgh")

    def test_one_real_mention_rescues_the_row(self) -> None:
        """A story can carry both. Counting it as noise because a title
        appears would trade one wrong number for another — which is why the
        rule is *every* mention, not *any*."""
        text = "The Duke of Edinburgh opened the new bridge in Edinburgh this morning"
        assert not is_collision(text, "edinburgh")

    def test_a_city_with_no_title_is_never_a_collision(self) -> None:
        assert not is_collision("Firefighters tackle large blaze in Lahore", "lahore")

    def test_absent_terms_are_not_collisions(self) -> None:
        assert not is_collision("Flooding closes roads across Fife", "edinburgh")


class TestCityProbe:
    def test_clean_removes_both_defects(self) -> None:
        probe = CityProbe(city="edinburgh", results=40, collisions=20, duplicates=2)
        assert probe.clean == 18
        assert probe.clean_share == pytest.approx(0.45)

    def test_an_empty_result_is_not_a_division_by_zero(self) -> None:
        assert CityProbe(city="nowhere").clean_share == 0.0

    def test_clean_never_goes_negative(self) -> None:
        """Defensive: a duplicate can also be a collision, so the two counts
        can exceed the result count on a pathological page."""
        probe = CityProbe(city="x", results=3, collisions=3, duplicates=2)
        assert probe.clean == 0

    def test_the_report_states_numbers_and_no_verdict(self) -> None:
        text = format_report([CityProbe(city="edinburgh", results=40, collisions=20)])
        assert "edinburgh" in text
        assert "40" in text
        #: No pass/fail language. The finding is the count; a threshold here
        #: would be a judgement this check is not entitled to make.
        for word in ("PASS", "FAIL", "OK", "BAD"):
            assert word not in text
