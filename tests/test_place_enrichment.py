"""Ground-level named-place enrichment tests (#745)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow, PlaceLookupRow
from app.enrichment.place import (
    PLACE_METHOD_VERSION,
    WIKIDATA_MAXLAG,
    PlaceCandidate,
    PlaceContext,
    enrich_news_places,
    extract_place_candidates,
    lookup_key,
    resolve_wikidata_place,
)
from app.models import Category, Event
from app.persistence import upsert_events

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)
EDINBURGH = PlaceContext(country="GB", city="Edinburgh", lat=55.9483, lon=-3.2191)


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class FakeWikidataClient:
    def __init__(
        self,
        search: list[dict[str, Any]],
        entities: dict[str, Any] | None = None,
        countries: dict[str, Any] | None = None,
    ) -> None:
        self.search = search
        self.entities = entities or {}
        self.countries = countries or {
            "Q145": {
                "claims": {
                    "P297": [{"mainsnak": {"datavalue": {"value": "GB"}}}],
                }
            }
        }
        self.calls: list[dict[str, Any]] = []

    def get(self, _url: str, *, params: dict[str, Any]) -> FakeResponse:
        self.calls.append(params)
        if params["action"] == "wbsearchentities":
            return FakeResponse({"search": self.search})
        if set(str(params["ids"]).split("|")).issubset(self.countries):
            return FakeResponse({"entities": self.countries})
        return FakeResponse({"entities": self.entities})


class FailingWikidataClient:
    def get(self, _url: str, *, params: dict[str, Any]) -> FakeResponse:
        raise httpx.ReadTimeout("temporary Wikidata timeout")


class MaxlagWikidataClient:
    def get(self, _url: str, *, params: dict[str, Any]) -> FakeResponse:
        return FakeResponse({"error": {"code": "maxlag", "info": "replicas are behind"}})


def _search_item(entity_id: str, text: str = "King's Theatre") -> dict[str, Any]:
    return {
        "id": entity_id,
        "label": text,
        "match": {"type": "label", "language": "en", "text": text},
    }


def _entity(
    label: str,
    description: str,
    lat: float | None,
    lon: float | None,
    country_id: str | None = "Q145",
) -> dict[str, Any]:
    claims: dict[str, Any] = {}
    if lat is not None and lon is not None:
        claims["P625"] = [
            {
                "rank": "normal",
                "mainsnak": {
                    "datavalue": {
                        "value": {"latitude": lat, "longitude": lon},
                    }
                },
            }
        ]
    if country_id:
        claims["P17"] = [
            {
                "mainsnak": {
                    "datavalue": {
                        "value": {"id": country_id},
                    }
                }
            }
        ]
    return {
        "labels": {"en": {"value": label}},
        "descriptions": {"en": {"value": description}},
        "claims": claims,
    }


def _rss_row(source_event_id: str, title: str, *, minutes_old: int = 5) -> EventRow:
    return EventRow(
        source="rss-bbc-uk",
        source_event_id=source_event_id,
        occurred_at=NOW - timedelta(minutes=minutes_old),
        fetched_at=NOW,
        category="news",
        severity=0.3,
        keywords=[],
        country="GB",
        lat=EDINBURGH.lat,
        lon=EDINBURGH.lon,
        payload={
            "title": title,
            "summary": "",
            "city": "Edinburgh",
            "geo_basis": "term",
            "entities": [],
        },
    )


def _event(source_event_id: str, title: str) -> Event:
    return Event(
        source="rss-bbc-uk",
        source_event_id=source_event_id,
        occurred_at=NOW,
        fetched_at=NOW,
        category=Category.NEWS,
        severity=0.3,
        country="GB",
        lat=EDINBURGH.lat,
        lon=EDINBURGH.lon,
        payload={
            "title": title,
            "summary": "",
            "city": "Edinburgh",
            "geo_basis": "term",
            "entities": [],
        },
    )


def _resolved_cache(title: str = "King's Theatre") -> PlaceLookupRow:
    candidate = PlaceCandidate(title, "building")
    return PlaceLookupRow(
        lookup_key=lookup_key(candidate, EDINBURGH),
        query_text=title,
        context_country="GB",
        context_city="Edinburgh",
        status="resolved",
        lat=55.9418715963841,
        lon=-3.20281137653343,
        precision="building",
        wikidata_id="Q6411122",
        label="King's Theatre",
        description="theatre in Edinburgh, Scotland, UK",
        checked_at=NOW,
        resolver_version=PLACE_METHOD_VERSION,
    )


def test_extracts_named_building_without_optional_ner() -> None:
    payload = {
        "title": "King's Theatre in Edinburgh re-opens after £41m refurbishment",
        "summary": "",
        "entities": [],
    }

    assert extract_place_candidates(payload, city="Edinburgh") == (
        PlaceCandidate("King's Theatre", "building"),
    )


def test_extracts_named_street_and_strips_leading_city_context() -> None:
    payload = {"title": "Edinburgh Leven Street closes after fire", "summary": ""}

    assert extract_place_candidates(payload, city="Edinburgh") == (
        PlaceCandidate("Leven Street", "street"),
    )


def test_two_explicit_places_remain_two_candidates() -> None:
    payload = {"title": "King's Theatre and Royal Albert Hall announce reopening", "summary": ""}

    assert extract_place_candidates(payload) == (
        PlaceCandidate("King's Theatre", "building"),
        PlaceCandidate("Royal Albert Hall", "building"),
    )


def test_resolver_selects_exact_edininburgh_building_not_search_rank() -> None:
    client = FakeWikidataClient(
        [_search_item("Q38280594"), _search_item("Q6411122"), _search_item("Q6411121")],
        {
            "Q38280594": _entity(
                "King's Theatre", "theatre in Annapolis Royal, Canada", 44.74, -65.51
            ),
            "Q6411122": _entity(
                "King's Theatre",
                "theatre in Edinburgh, Scotland, UK",
                55.9418715963841,
                -3.20281137653343,
            ),
            "Q6411121": _entity(
                "King's Theatre", "theatre in Glasgow, Scotland, UK", 55.864, -4.252
            ),
        },
    )

    verdict = resolve_wikidata_place(
        PlaceCandidate("King's Theatre", "building"),
        EDINBURGH,
        client=client,  # type: ignore[arg-type]
    )

    assert verdict.status == "resolved"
    assert verdict.resolution is not None
    assert verdict.resolution.wikidata_id == "Q6411122"
    assert (verdict.resolution.lat, verdict.resolution.lon) == (
        55.9418715963841,
        -3.20281137653343,
    )
    assert [call["action"] for call in client.calls] == [
        "wbsearchentities",
        "wbgetentities",
        "wbgetentities",
    ]
    assert all(call["maxlag"] == WIKIDATA_MAXLAG for call in client.calls)


def test_resolver_rejects_non_exact_search_match_without_entity_fetch() -> None:
    client = FakeWikidataClient([_search_item("Q1", "King Theatre")])

    verdict = resolve_wikidata_place(
        PlaceCandidate("King's Theatre", "building"),
        EDINBURGH,
        client=client,  # type: ignore[arg-type]
    )

    assert verdict.status == "no_match"
    assert len(client.calls) == 1


def test_resolver_treats_http_200_maxlag_as_retry_not_no_match() -> None:
    try:
        resolve_wikidata_place(
            PlaceCandidate("King's Theatre", "building"),
            EDINBURGH,
            client=MaxlagWikidataClient(),  # type: ignore[arg-type]
        )
    except ValueError as exc:
        assert "maxlag" in str(exc)
    else:
        raise AssertionError("maxlag was incorrectly cached as a place miss")


def test_resolver_keeps_two_same_city_exact_matches_ambiguous() -> None:
    client = FakeWikidataClient(
        [_search_item("Q1"), _search_item("Q2")],
        {
            "Q1": _entity("King's Theatre", "theatre in Edinburgh", 55.941, -3.20),
            "Q2": _entity("King's Theatre", "former theatre in Edinburgh", 55.95, -3.18),
        },
    )

    verdict = resolve_wikidata_place(
        PlaceCandidate("King's Theatre", "building"),
        EDINBURGH,
        client=client,  # type: ignore[arg-type]
    )

    assert verdict.status == "ambiguous"
    assert verdict.resolution is None


def test_resolver_rejects_place_in_wrong_country_even_when_city_text_matches() -> None:
    client = FakeWikidataClient(
        [_search_item("Q1")],
        {
            "Q1": _entity(
                "King's Theatre",
                "theatre in Edinburgh",
                55.941,
                -3.20,
                country_id="Q16",
            )
        },
        countries={"Q16": {"claims": {"P297": [{"mainsnak": {"datavalue": {"value": "CA"}}}]}}},
    )

    verdict = resolve_wikidata_place(
        PlaceCandidate("King's Theatre", "building"),
        EDINBURGH,
        client=client,  # type: ignore[arg-type]
    )

    assert verdict.status == "no_match"


def test_worker_resolves_once_then_reuses_cache_for_same_place(db_session: Session) -> None:
    db_session.add_all(
        [
            _rss_row("one", "King's Theatre in Edinburgh re-opens"),
            _rss_row("two", "Fire contained at King's Theatre in Edinburgh", minutes_old=6),
        ]
    )
    db_session.commit()
    client = FakeWikidataClient(
        [_search_item("Q6411122")],
        {
            "Q6411122": _entity(
                "King's Theatre", "theatre in Edinburgh, Scotland, UK", 55.94187, -3.20281
            )
        },
    )

    stats = enrich_news_places(
        db_session,
        limit=10,
        client=client,
        now=NOW,  # type: ignore[arg-type]
    )
    db_session.commit()

    rows = db_session.execute(select(EventRow).order_by(EventRow.source_event_id)).scalars().all()
    assert stats["lookups"] == 1
    assert stats["cache_hits"] == 1
    assert stats["enriched"] == 2
    assert len(client.calls) == 3
    assert {(row.lat, row.lon) for row in rows} == {(55.94187, -3.20281)}
    assert {row.payload["geo_basis"] for row in rows} == {"place"}
    assert {row.payload["geo_precision"] for row in rows} == {"building"}
    assert {row.payload["geo_source"] for row in rows} == {"wikidata"}
    assert {row.payload["place_wikidata_id"] for row in rows} == {"Q6411122"}
    assert db_session.execute(select(PlaceLookupRow)).scalars().one().status == "resolved"


def test_worker_negative_result_is_cached(db_session: Session) -> None:
    db_session.add_all(
        [
            _rss_row("one", "King's Theatre in Edinburgh re-opens"),
            _rss_row("two", "Fire contained at King's Theatre in Edinburgh", minutes_old=6),
        ]
    )
    db_session.commit()
    client = FakeWikidataClient([])

    stats = enrich_news_places(
        db_session,
        limit=10,
        client=client,
        now=NOW,  # type: ignore[arg-type]
    )
    db_session.commit()

    assert stats["lookups"] == 1
    assert stats["cache_hits"] == 1
    assert len(client.calls) == 1
    assert db_session.execute(select(PlaceLookupRow)).scalars().one().status == "no_match"


def test_worker_does_not_cache_network_error_and_retries_next_run(db_session: Session) -> None:
    db_session.add(_rss_row("one", "King's Theatre in Edinburgh re-opens"))
    db_session.commit()

    failed = enrich_news_places(
        db_session,
        limit=10,
        client=FailingWikidataClient(),  # type: ignore[arg-type]
        now=NOW,
    )
    db_session.commit()
    row = db_session.execute(select(EventRow)).scalars().one()
    assert failed["errors"] == 1
    assert row.payload.get("place_model") is None
    assert db_session.execute(select(PlaceLookupRow)).scalars().all() == []

    recovered_client = FakeWikidataClient(
        [_search_item("Q6411122")],
        {
            "Q6411122": _entity(
                "King's Theatre", "theatre in Edinburgh, Scotland, UK", 55.94187, -3.20281
            )
        },
    )
    recovered = enrich_news_places(
        db_session,
        limit=10,
        client=recovered_client,  # type: ignore[arg-type]
        now=NOW + timedelta(minutes=30),
    )
    db_session.commit()

    assert recovered["enriched"] == 1
    assert db_session.execute(select(PlaceLookupRow)).scalars().one().status == "resolved"


def test_cached_place_survives_rss_refresh_and_changed_title_withdraws_it(
    db_session: Session,
) -> None:
    db_session.add(_resolved_cache())
    db_session.commit()

    upsert_events([_event("story", "King's Theatre in Edinburgh re-opens")], db_session)
    db_session.commit()
    row = db_session.execute(select(EventRow)).scalars().one()
    assert (row.lat, row.lon) == (55.9418715963841, -3.20281137653343)
    assert row.payload["geo_basis"] == "place"

    upsert_events([_event("story", "Edinburgh council publishes budget")], db_session)
    db_session.commit()
    db_session.expire_all()
    row = db_session.execute(select(EventRow)).scalars().one()
    assert (row.lat, row.lon) == (EDINBURGH.lat, EDINBURGH.lon)
    assert row.payload["geo_basis"] == "term"
    assert row.payload.get("place_wikidata_id") is None
    assert row.payload["geo_precision"] == "city"
