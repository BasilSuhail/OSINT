"""A peerage is not a place (#771).

The resolver's city layer matches a gazetteer name anywhere in the text, so a
royal title puts a story on a map. Ninety-nine rows in the live table are
placed this way, and the pins are not subtle:

```
Sarah Ferguson's secret meeting at royal house   -> 39.963,-76.728   York, Pennsylvania
Prince Edward makes King Charles proud           -> 55.948,-3.219    Edinburgh
```

The rule for deciding this already exists. `app.enrichment.name_collision` was
written for #800, where searching "edinburgh" returned twenty rows about a
dukedom, and it is deliberately shared rather than reimplemented: two copies
of a fiddly rule drift, and then the number stops describing the product.

What is new here is applying it where the coordinate is assigned, instead of
only where results are listed.
"""

from __future__ import annotations

from app.enrichment.geo import resolve_geo


class TestHonorificsAreNotPlaces:
    def test_a_dukedom_does_not_place_a_story(self) -> None:
        verdict = resolve_geo(
            "Duke of Edinburgh title passes to Prince Edward",
            "The palace confirmed the peerage on Friday.",
        )
        assert verdict.city != "Edinburgh"
        assert verdict.lat is None and verdict.lon is None

    def test_a_duchess_does_not_place_a_story(self) -> None:
        verdict = resolve_geo(
            "Sarah Ferguson's secret meeting at royal house",
            "The Duchess of York was seen arriving on Tuesday.",
        )
        assert verdict.city != "York"
        assert verdict.lat is None and verdict.lon is None

    def test_an_award_that_borrows_the_name_does_not_place_a_story(self) -> None:
        """The expedition in this one happened in Snowdonia."""
        verdict = resolve_geo(
            "Tributes to teenager who died during Duke of Edinburgh expedition",
            "",
        )
        assert verdict.city != "Edinburgh"


class TestRealPlacesStillResolve:
    def test_a_plain_locative_still_resolves(self) -> None:
        verdict = resolve_geo(
            "Police make 49 arrests in Edinburgh city centre crackdown",
            "Officers from the new unit were deployed in Edinburgh.",
        )
        assert verdict.city == "Edinburgh"
        assert verdict.lat is not None

    def test_a_story_carrying_both_is_about_the_place(self) -> None:
        """ "Every" mention must be a title before the city is refused. A story
        that says both is about the place, and dropping it would trade one
        wrong answer for another."""
        verdict = resolve_geo(
            "Duke of Edinburgh opens new hospital wing in Edinburgh",
            "The ceremony took place in Edinburgh this morning.",
        )
        assert verdict.city == "Edinburgh"
        assert verdict.lat is not None

    def test_an_unrelated_city_is_untouched(self) -> None:
        verdict = resolve_geo("Fire breaks out at warehouse in Glasgow", "")
        assert verdict.city == "Glasgow"


class TestTheCountryIsNotLostWithTheCoordinate:
    def test_a_royal_story_can_still_be_british(self) -> None:
        """Refusing the pin must not refuse the country: the term layer
        resolved this correctly before the city layer was consulted, and that
        verdict is still the right one."""
        verdict = resolve_geo(
            "Duke of Edinburgh title passes to Prince Edward",
            "Buckingham Palace said the UK ceremony would be private.",
        )
        assert verdict.iso == "GB"
        assert verdict.lat is None, "a country is not a point"
