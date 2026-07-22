"""The harm scale and its verdicts (#591).

Harsh means refusing to soften real harm, not inflating everything. #580 found
55% of hazard country-months pinned at 0.90 — degenerate at the top is as
useless as degenerate at the bottom.
"""

from __future__ import annotations

import pytest

from app.severity import scale


class TestBands:
    def test_bands_tile_the_whole_range_without_gaps_or_overlap(self):
        edges = [band.lower for band in scale.BANDS] + [scale.BANDS[-1].upper]

        assert edges == sorted(edges)
        assert edges[0] == 0.0
        assert edges[-1] == 1.0
        for band, nxt in zip(scale.BANDS, scale.BANDS[1:], strict=False):
            assert band.upper == nxt.lower

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0.0, "routine"),
            (0.15, "routine"),
            (0.30, "tension"),
            (0.50, "violence"),
            (0.65, "grave"),
            (0.80, "mass_casualty"),
            (1.0, "mass_casualty"),
        ],
    )
    def test_classifies_a_value_into_its_band(self, value, expected):
        assert scale.band_for(value).name == expected

    def test_a_confirmed_death_cannot_score_below_the_lethal_floor(self):
        """The point of the scale: death never reads as routine."""
        assert scale.LETHAL_FLOOR == 0.60
        assert scale.band_for(scale.LETHAL_FLOOR).name == "grave"

    def test_mass_casualty_floor_is_where_ten_or_more_deaths_land(self):
        assert scale.MASS_CASUALTY_FLOOR == 0.80
        assert scale.band_for(scale.MASS_CASUALTY_FLOOR).name == "mass_casualty"

    def test_rejects_values_outside_the_range(self):
        with pytest.raises(ValueError):
            scale.band_for(1.5)
        with pytest.raises(ValueError):
            scale.band_for(-0.1)


class TestVerdict:
    def test_carries_value_rationale_and_method(self):
        verdict = scale.Verdict(value=0.85, rationale="M7.1 at 18km depth", method="usgs-magnitude")

        assert (verdict.value, verdict.method) == (0.85, "usgs-magnitude")
        assert verdict.band == "mass_casualty"

    def test_refuses_an_empty_rationale(self):
        """A score with no stated reason is the thing this exists to prevent."""
        with pytest.raises(ValueError):
            scale.Verdict(value=0.5, rationale="   ", method="x")

    def test_refuses_a_value_out_of_range(self):
        with pytest.raises(ValueError):
            scale.Verdict(value=1.4, rationale="whatever", method="x")

    def test_serialises_into_the_payload_shape_the_fetchers_store(self):
        verdict = scale.Verdict(value=0.7, rationale="3 killed in attack", method="news-llm")

        assert verdict.as_payload() == {
            "severity_rationale": "3 killed in attack",
            "severity_method": "news-llm",
            "severity_band": "grave",
        }


class TestNoEuphemism:
    """No cake words: the rationale must say what happened (#591)."""

    @pytest.mark.parametrize(
        "softened", ["incident occurred", "a situation developed", "an event took place"]
    )
    def test_flags_euphemism_in_a_lethal_rationale(self, softened):
        assert scale.euphemism_in(softened, value=0.7) is not None

    def test_accepts_a_blunt_rationale(self):
        assert scale.euphemism_in("12 killed in a market bombing", value=0.85) is None

    def test_does_not_police_low_severity_rationales(self):
        """'Routine incident' is fine when the score says routine."""
        assert scale.euphemism_in("incident occurred", value=0.1) is None
