"""A city centroid is not an exact point (#773).

The Edinburgh viewport had 143 rows stacked on two coordinates that are not
places — they are the gazetteer's idea of where "Edinburgh" is — drawn
identically to a row standing on a verified building. Over seven days, 181 of
31,361 positioned rows are on a place somebody verified; the rest are
centroids of cities, administrative areas and countries.

The row already knows which it is. `geo_basis` records how the coordinate was
arrived at and `geo_precision` what the geocoder thought it had found. Nothing
downstream read either, so the map could not tell a reader the difference.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import app, get_session
from app.db_models import EventRow
from app.location_precision import precision_of, radius_m


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


class TestVerdicts:
    def test_a_verified_venue_is_exact(self) -> None:
        payload = {"geo_basis": "place", "geo_precision": "building"}
        assert precision_of("rss-edinburgh-live", payload, positioned=True) == "exact"

    def test_a_named_city_is_a_city(self) -> None:
        payload = {"geo_basis": "city", "geo_precision": "city"}
        assert precision_of("rss-edinburgh-live", payload, positioned=True) == "city"

    def test_a_region_anchor_is_an_area(self) -> None:
        assert precision_of("rss-stv-news", {"geo_basis": "region"}, positioned=True) == "area"

    def test_a_country_term_is_a_country(self) -> None:
        assert precision_of("rss-bbc-uk", {"geo_basis": "term"}, positioned=True) == "country"

    def test_gdelt_uses_its_own_geocoder_precision(self) -> None:
        for coded, expected in (
            ("building", "exact"),
            ("street", "exact"),
            ("city", "city"),
            ("admin", "area"),
            ("country", "country"),
        ):
            assert precision_of("gdelt", {"geo_precision": coded}, positioned=True) == expected

    def test_the_looser_of_two_claims_wins(self) -> None:
        """A `city` basis whose gazetteer hit was only country-precise is a
        country claim. Taking the tighter one would overstate it."""
        payload = {"geo_basis": "city", "geo_precision": "country"}
        assert precision_of("gdelt", payload, positioned=True) == "country"

    def test_an_instrument_reading_is_exact(self) -> None:
        """An epicentre and a fire pixel are measurements, not geocodes."""
        for source in ("usgs-quake", "nasa-firms", "opensky-adsb"):
            assert precision_of(source, {}, positioned=True) == "exact", source

    def test_an_unpositioned_row_claims_nothing(self) -> None:
        payload = {"geo_basis": "place", "geo_precision": "building"}
        assert precision_of("rss-bbc-uk", payload, positioned=False) == "unknown"
        assert radius_m("unknown") == 0


class TestRadius:
    def test_the_radius_grows_with_the_vagueness(self) -> None:
        assert radius_m("exact") < radius_m("city") < radius_m("area") < radius_m("country"), (
            "a vaguer claim must not be drawn tighter"
        )

    def test_an_exact_point_still_claims_something(self) -> None:
        """Not zero: a verified building is a building, not a mathematical
        point, and a reader should not be told otherwise either."""
        assert radius_m("exact") > 0


class TestThroughTheApi:
    def _row(self, source: str, payload: dict, *, positioned: bool = True) -> EventRow:
        from datetime import UTC, datetime

        return EventRow(
            source=source,
            source_event_id=f"{source}-{payload.get('geo_basis')}-{positioned}",
            occurred_at=datetime(2026, 8, 8, 12, tzinfo=UTC),
            category="geopolitical",
            keywords=[],
            lat=55.95 if positioned else None,
            lon=-3.2 if positioned else None,
            payload=payload | {"title": "A story"},
        )

    def test_every_row_says_how_precise_it_is(self, db_session):
        db_session.add_all(
            [
                self._row(
                    "rss-edinburgh-live", {"geo_basis": "place", "geo_precision": "building"}
                ),
                self._row("rss-stv-news", {"geo_basis": "city", "geo_precision": "city"}),
                self._row("rss-bbc-uk", {"geo_basis": "term"}),
            ]
        )
        db_session.commit()
        app.dependency_overrides[get_session] = lambda: db_session
        rows = {r["source"]: r for r in TestClient(app).get("/events").json()}
        assert rows["rss-edinburgh-live"]["location_precision"] == "exact"
        assert rows["rss-stv-news"]["location_precision"] == "city"
        assert rows["rss-bbc-uk"]["location_precision"] == "country"

    def test_the_radius_travels_with_it(self, db_session):
        db_session.add(self._row("rss-stv-news", {"geo_basis": "city", "geo_precision": "city"}))
        db_session.commit()
        app.dependency_overrides[get_session] = lambda: db_session
        row = TestClient(app).get("/events").json()[0]
        assert row["location_radius_m"] == radius_m("city")

    def test_a_coordless_row_claims_no_radius(self, db_session):
        db_session.add(self._row("rss-bbc-uk", {"geo_basis": "none"}, positioned=False))
        db_session.commit()
        app.dependency_overrides[get_session] = lambda: db_session
        row = TestClient(app).get("/events").json()[0]
        assert row["location_precision"] == "unknown"
        assert row["location_radius_m"] == 0
