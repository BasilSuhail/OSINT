"""Tests for `app.sources.uk_police_fetcher`."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.models import Category
from app.sources.uk_police_fetcher import (
    CRIME_SEVERITY,
    DEFAULT_PANEL,
    UKCity,
    UKPoliceFetcher,
    _severity_for,
    crime_to_event,
    parse_crime_list,
)

LONDON = UKCity("London", 51.5074, -0.1278)


def _make_crime(
    *,
    rec_id: int = 134239163,
    category: str = "violent-crime",
    lat: str = "51.510345",
    lon: str = "-0.122502",
    month: str = "2026-03",
    street: str = "On or near Theatre/concert Hall",
    outcome: str | None = None,
    context: str = "",
) -> dict:
    return {
        "category": category,
        "location_type": "Force",
        "location": {
            "latitude": lat,
            "street": {"id": 1679211, "name": street},
            "longitude": lon,
        },
        "context": context,
        "outcome_status": ({"category": outcome} if outcome else None),
        "persistent_id": "",
        "id": rec_id,
        "location_subtype": "",
        "month": month,
    }


class TestSeverity:
    def test_violent_crime_high(self) -> None:
        assert _severity_for("violent-crime") == CRIME_SEVERITY["violent-crime"]

    def test_anti_social_low(self) -> None:
        assert _severity_for("anti-social-behaviour") == CRIME_SEVERITY["anti-social-behaviour"]

    def test_unknown_default(self) -> None:
        assert _severity_for("absolutely-unknown") == 0.4

    def test_empty_default(self) -> None:
        assert _severity_for("") == 0.4
        assert _severity_for(None) == 0.4


class TestCrimeToEvent:
    def test_basic_violent_crime(self) -> None:
        ev = crime_to_event(_make_crime(), city=LONDON, fetched_at=datetime.now(UTC))
        assert ev is not None
        assert ev.source == "uk-police"
        assert ev.source_event_id == "134239163"
        assert ev.category == Category.NEWS
        assert ev.severity == CRIME_SEVERITY["violent-crime"]
        assert ev.country == "GB"
        assert ev.lat == pytest.approx(51.510345)
        assert ev.lon == pytest.approx(-0.122502)
        assert ev.occurred_at == datetime(2026, 3, 1, tzinfo=UTC)
        assert ev.payload["title"] == "Violent Crime"
        assert ev.payload["category_raw"] == "violent-crime"
        assert ev.payload["city"] == "London"
        assert ev.payload["street"] == "On or near Theatre/concert Hall"

    def test_missing_id_skipped(self) -> None:
        bad = _make_crime()
        bad["id"] = None
        ev = crime_to_event(bad, city=LONDON, fetched_at=datetime.now(UTC))
        assert ev is None

    def test_bad_coords_skipped(self) -> None:
        bad = _make_crime(lat="not-a-number")
        ev = crime_to_event(bad, city=LONDON, fetched_at=datetime.now(UTC))
        assert ev is None

    def test_bad_month_falls_back_to_fetched_at(self) -> None:
        fetched_at = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
        ev = crime_to_event(_make_crime(month="bad"), city=LONDON, fetched_at=fetched_at)
        assert ev is not None
        assert ev.occurred_at == fetched_at

    def test_outcome_included(self) -> None:
        ev = crime_to_event(
            _make_crime(outcome="Investigation complete; no suspect"),
            city=LONDON,
            fetched_at=datetime.now(UTC),
        )
        assert ev is not None
        assert ev.payload["outcome"] == "Investigation complete; no suspect"


class TestParseCrimeList:
    def test_parses_multi(self) -> None:
        records = [
            _make_crime(rec_id=1),
            _make_crime(rec_id=2, category="anti-social-behaviour"),
            {"bogus": True},  # malformed → skipped
        ]
        out = parse_crime_list(records, city=LONDON, fetched_at=datetime.now(UTC))
        assert [e.source_event_id for e in out] == ["1", "2"]
        assert out[1].severity == CRIME_SEVERITY["anti-social-behaviour"]

    def test_non_list_returns_empty(self) -> None:
        # type: ignore-style hammering
        assert parse_crime_list({"not": "a list"}, city=LONDON, fetched_at=datetime.now(UTC)) == []  # type: ignore[arg-type]


class TestPanel:
    def test_default_panel_is_england_wales_only(self) -> None:
        names = {c.name for c in DEFAULT_PANEL}
        # Edinburgh / Glasgow / Belfast should NOT be in the panel — Scotland
        # and Northern Ireland are not on data.police.uk.
        assert "Edinburgh" not in names
        assert "Glasgow" not in names
        assert "Belfast" not in names
        # London / Manchester / Birmingham / Liverpool / Leeds / Bristol — yes.
        assert names == {"London", "Manchester", "Birmingham", "Liverpool", "Leeds", "Bristol"}


class TestFetcherHttp:
    @respx.mock
    def test_fetch_round_trip(self) -> None:
        respx.get("https://data.police.uk/api/crime-last-updated").mock(
            return_value=httpx.Response(200, json={"date": "2026-03-01"})
        )
        # Each city's crimes-street call. All return the same payload here.
        respx.get(url__regex=r"https://data\.police\.uk/api/crimes-street/all-crime.*").mock(
            return_value=httpx.Response(
                200,
                json=[_make_crime(rec_id=10), _make_crime(rec_id=11)],
            )
        )
        events = UKPoliceFetcher().fetch()
        # 6 cities x 2 records each (responses use string ids, dedup happens at
        # the DB layer so the parser keeps duplicates).
        assert len(events) == 6 * 2

    @respx.mock
    def test_5xx_raises(self) -> None:
        respx.get("https://data.police.uk/api/crime-last-updated").mock(
            return_value=httpx.Response(200, json={"date": "2026-03-01"})
        )
        respx.get(url__regex=r"https://data\.police\.uk/api/crimes-street/all-crime.*").mock(
            return_value=httpx.Response(503)
        )
        with pytest.raises(httpx.HTTPStatusError):
            UKPoliceFetcher().fetch()

    def test_rejects_non_positive_timeout(self) -> None:
        with pytest.raises(ValueError):
            UKPoliceFetcher(timeout_seconds=0)

    def test_rejects_empty_panel(self) -> None:
        with pytest.raises(ValueError):
            UKPoliceFetcher(cities=())

    def test_archive_path(self) -> None:
        path = UKPoliceFetcher().archive_path()
        assert path.startswith("/mnt/data/parquet/uk-police/year=")
