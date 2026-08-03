"""Ground-level named-place enrichment tests (#745)."""

from __future__ import annotations

import hashlib
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
    PlaceCandidateRejection,
    PlaceContext,
    enrich_news_places,
    extract_place_candidates,
    extract_place_evidence,
    lookup_key,
    repair_generic_place_names,
    resolve_wikidata_place,
)
from app.models import Category, Event
from app.persistence import upsert_events

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)
EDINBURGH = PlaceContext(country="GB", city="Edinburgh", lat=55.9483, lon=-3.2191)
COUNTRY_ONLY_GB = PlaceContext(country="GB")


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


class MappedWikidataClient(FakeWikidataClient):
    """Return candidate-specific searches while sharing fetched entities."""

    def __init__(
        self,
        searches: dict[str, list[dict[str, Any]]],
        entities: dict[str, Any],
        countries: dict[str, Any] | None = None,
    ) -> None:
        super().__init__([], entities, countries)
        self.searches = searches

    def get(self, url: str, *, params: dict[str, Any]) -> FakeResponse:
        if params["action"] == "wbsearchentities":
            self.calls.append(params)
            return FakeResponse({"search": self.searches.get(str(params["search"]), [])})
        return super().get(url, params=params)


class LanguageMappedWikidataClient(FakeWikidataClient):
    """Return one search fixture per candidate language."""

    def __init__(
        self,
        searches: dict[str, list[dict[str, Any]]],
        entities: dict[str, Any],
        countries: dict[str, Any],
    ) -> None:
        super().__init__([], entities, countries)
        self.searches = searches

    def get(self, url: str, *, params: dict[str, Any]) -> FakeResponse:
        if params["action"] == "wbsearchentities":
            self.calls.append(params)
            return FakeResponse({"search": self.searches.get(str(params["language"]), [])})
        return super().get(url, params=params)


class FailingWikidataClient:
    def get(self, _url: str, *, params: dict[str, Any]) -> FakeResponse:
        raise httpx.ReadTimeout("temporary Wikidata timeout")


class MaxlagWikidataClient:
    def get(self, _url: str, *, params: dict[str, Any]) -> FakeResponse:
        return FakeResponse({"error": {"code": "maxlag", "info": "replicas are behind"}})


def _search_item(
    entity_id: str,
    text: str = "King's Theatre",
    *,
    language: str = "en",
    match_type: str = "label",
) -> dict[str, Any]:
    return {
        "id": entity_id,
        "label": text,
        "match": {"type": match_type, "language": language, "text": text},
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


def _country_only_row(
    source_event_id: str,
    title: str,
    *,
    country: str = "GB",
    entities: list[dict[str, str]] | None = None,
) -> EventRow:
    return EventRow(
        source="rss-bbc-uk",
        source_event_id=source_event_id,
        occurred_at=NOW - timedelta(minutes=5),
        fetched_at=NOW,
        category="news",
        severity=0.3,
        keywords=[],
        country=country,
        lat=None,
        lon=None,
        payload={
            "title": title,
            "summary": "",
            "geo_basis": "term",
            "entities": entities or [],
        },
    )


def _country_only_event(
    source_event_id: str,
    title: str,
    *,
    country: str = "GB",
    entities: list[dict[str, str]] | None = None,
) -> Event:
    return Event(
        source="rss-bbc-uk",
        source_event_id=source_event_id,
        occurred_at=NOW,
        fetched_at=NOW,
        category=Category.NEWS,
        severity=0.3,
        country=country,
        lat=None,
        lon=None,
        payload={
            "title": title,
            "summary": "",
            "geo_basis": "term",
            "entities": entities or [],
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


def _country_only_resolved_cache(title: str = "Wembley Stadium") -> PlaceLookupRow:
    candidate = PlaceCandidate(title, "building")
    return PlaceLookupRow(
        lookup_key=lookup_key(candidate, COUNTRY_ONLY_GB),
        query_text=title,
        context_country="GB",
        context_city="",
        status="resolved",
        lat=51.556,
        lon=-0.2796,
        precision="building",
        wikidata_id="Q193633",
        label="Wembley Stadium",
        description="football stadium in London, England",
        checked_at=NOW,
        resolver_version=PLACE_METHOD_VERSION,
    )


def _resolved_country_cache(
    name: str,
    wikidata_id: str,
    lat: float,
    lon: float,
) -> PlaceLookupRow:
    candidate = PlaceCandidate(name, "building")
    return PlaceLookupRow(
        lookup_key=lookup_key(candidate, COUNTRY_ONLY_GB),
        query_text=name,
        context_country="GB",
        context_city="",
        status="resolved",
        lat=lat,
        lon=lon,
        precision="building",
        wikidata_id=wikidata_id,
        label=name,
        description=f"verified {name}",
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


def test_preserves_city_prefix_when_it_distinguishes_generic_place_class() -> None:
    cases = (
        ("New York", "New York City Hall"),
        ("Kolkata", "Kolkata High Court"),
        ("Sydney", "Sydney Central Station"),
        ("London", "London General Hospital"),
    )

    for city, name in cases:
        evidence = extract_place_evidence(
            {"title": f"Update from {name}", "summary": ""}, city=city
        )
        assert evidence.candidates == (PlaceCandidate(name, "building"),)
        assert evidence.rejections == ()


def test_does_not_join_title_city_to_generic_name_in_summary() -> None:
    evidence = extract_place_evidence(
        {
            "title": "Breaking news in Liverpool",
            "summary": "Magistrates' Court hearing adjourned",
        },
        city="Liverpool",
    )

    assert evidence.candidates == ()
    assert evidence.rejections == (
        PlaceCandidateRejection("Magistrates' Court", "generic_institution_class"),
    )


def test_two_explicit_places_remain_two_candidates() -> None:
    payload = {"title": "King's Theatre and Royal Albert Hall announce reopening", "summary": ""}

    assert extract_place_candidates(payload) == (
        PlaceCandidate("King's Theatre", "building"),
        PlaceCandidate("Royal Albert Hall", "building"),
    )


def test_rejects_bare_institution_classes_before_lookup() -> None:
    names = (
        "Magistrates' Court",
        "City Hall",
        "General Hospital",
        "Central Station",
        "Crown Court",
        "County Jail",
        "High Court",
        "the Airport",
    )

    for name in names:
        evidence = extract_place_evidence({"title": f"Incident reported at {name}", "summary": ""})
        assert evidence.candidates == ()
        assert len(evidence.rejections) == 1
        assert evidence.rejections[0].reason == "generic_institution_class"


def test_generic_rule_preserves_proper_place_names() -> None:
    names = (
        "Brooklyn Bridge",
        "Atatürk Airport",
        "Mullaperiyar Dam",
        "BK Arena",
        "Dalal Street",
        "Damietta Port",
        "Mahara Prison",
        "Kaziranga National Park",
        "Hongik University",
        "Karnataka High Court",
        "King's Theatre",
    )

    for name in names:
        evidence = extract_place_evidence({"title": f"Update from {name}", "summary": ""})
        assert evidence.candidates
        assert evidence.rejections == ()


def test_extracts_bounded_accented_and_local_script_places() -> None:
    cases = (
        (
            "Hôpital Saint-Louis rouvre après travaux",
            PlaceCandidate("Hôpital Saint-Louis", "building", ("fr",)),
        ),
        (
            "стадион Лужники вновь открыт после ремонта",
            PlaceCandidate("стадион Лужники", "building", ("ru",)),
        ),
        (
            "إغلاق مطار بغداد الدولي بعد إنذار",
            PlaceCandidate("مطار بغداد الدولي", "building", ("ar",)),
        ),
        (
            "इंदिरा गांधी अंतरराष्ट्रीय हवाई अड्डा बंद",
            PlaceCandidate(
                "इंदिरा गांधी अंतरराष्ट्रीय हवाई अड्डा",
                "building",
                ("hi",),
            ),
        ),
    )

    for title, expected in cases:
        assert extract_place_candidates({"title": title, "summary": ""}) == (expected,)


def test_shared_kind_uses_only_its_bounded_language_fallback() -> None:
    candidates = extract_place_candidates({"title": "Avenida Paulista reabre hoy", "summary": ""})

    assert candidates == (PlaceCandidate("Avenida Paulista", "street", ("es", "pt")),)
    assert lookup_key(candidates[0], PlaceContext(country="ES")) != lookup_key(
        PlaceCandidate("Avenida Paulista", "street", ("es",)),
        PlaceContext(country="ES"),
    )


def test_unsupported_script_without_supported_place_kind_stays_absent() -> None:
    payload = {"title": "北京大学发布新研究", "summary": "", "entities": []}

    assert extract_place_candidates(payload) == ()


def test_candidate_rejects_unbounded_language_fallback() -> None:
    try:
        PlaceCandidate("Hospital Universitario", "building", ("es", "pt", "fr", "de"))
    except ValueError as exc:
        assert "exceeds" in str(exc)
    else:
        raise AssertionError("unbounded Wikidata fallback was accepted")


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


def test_resolver_accepts_exact_local_alias_and_preserves_local_label() -> None:
    candidate = PlaceCandidate("стадион Лужники", "building", ("ru",))
    entity = _entity("Luzhniki Stadium", "stadium in Moscow", 55.7158, 37.5537, "Q159")
    entity["labels"]["ru"] = {"value": "стадион Лужники"}
    entity["descriptions"]["ru"] = {"value": "стадион в Москве"}
    client = FakeWikidataClient(
        [_search_item("Q142536", candidate.name, language="ru", match_type="alias")],
        {"Q142536": entity},
        countries={"Q159": {"claims": {"P297": [{"mainsnak": {"datavalue": {"value": "RU"}}}]}}},
    )

    verdict = resolve_wikidata_place(
        candidate,
        PlaceContext(country="RU"),
        client=client,  # type: ignore[arg-type]
    )

    assert verdict.status == "resolved"
    assert verdict.resolution is not None
    assert verdict.resolution.label == "стадион Лужники"
    assert client.calls[0]["search"] == candidate.name
    assert client.calls[0]["language"] == "ru"
    assert client.calls[1]["languages"] == "ru|en"


def test_resolver_rejects_transliteration_as_identity_proof() -> None:
    client = FakeWikidataClient(
        [_search_item("Q1", "Baghdad International Airport", language="ar")]
    )

    verdict = resolve_wikidata_place(
        PlaceCandidate("مطار بغداد الدولي", "building", ("ar",)),
        PlaceContext(country="IQ"),
        client=client,  # type: ignore[arg-type]
    )

    assert verdict.status == "no_match"
    assert len(client.calls) == 1


def test_resolver_rejects_exact_text_from_unqueried_language() -> None:
    client = FakeWikidataClient([_search_item("Q1", "مطار بغداد الدولي", language="en")])

    verdict = resolve_wikidata_place(
        PlaceCandidate("مطار بغداد الدولي", "building", ("ar",)),
        PlaceContext(country="IQ"),
        client=client,  # type: ignore[arg-type]
    )

    assert verdict.status == "no_match"
    assert len(client.calls) == 1


def test_resolver_keeps_cross_language_exact_entities_ambiguous() -> None:
    entities = {
        "Q1": _entity("Paulista Avenue", "avenue in São Paulo", -23.56, -46.65, "Q155"),
        "Q2": _entity("Paulista Avenue", "former avenue in São Paulo", -23.57, -46.64, "Q155"),
    }
    for entity in entities.values():
        entity["labels"]["es"] = {"value": "Avenida Paulista"}
    client = LanguageMappedWikidataClient(
        {
            "es": [_search_item("Q1", "Avenida Paulista", language="es")],
            "pt": [_search_item("Q2", "Avenida Paulista", language="pt")],
        },
        entities,
        countries={"Q155": {"claims": {"P297": [{"mainsnak": {"datavalue": {"value": "BR"}}}]}}},
    )

    verdict = resolve_wikidata_place(
        PlaceCandidate("Avenida Paulista", "street", ("es", "pt")),
        PlaceContext(country="BR"),
        client=client,  # type: ignore[arg-type]
    )

    assert verdict.status == "ambiguous"
    assert [call["language"] for call in client.calls[:2]] == ["es", "pt"]


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


def test_country_only_resolver_selects_one_exact_country_match() -> None:
    client = FakeWikidataClient(
        [_search_item("Q193633", "Wembley Stadium")],
        {
            "Q193633": _entity(
                "Wembley Stadium",
                "football stadium in London, England",
                51.556,
                -0.2796,
            )
        },
    )

    verdict = resolve_wikidata_place(
        PlaceCandidate("Wembley Stadium", "building"),
        COUNTRY_ONLY_GB,
        client=client,  # type: ignore[arg-type]
    )

    assert verdict.status == "resolved"
    assert verdict.resolution is not None
    assert verdict.resolution.wikidata_id == "Q193633"


def test_country_only_resolver_keeps_same_country_names_ambiguous() -> None:
    client = FakeWikidataClient(
        [_search_item("Q1"), _search_item("Q2")],
        {
            "Q1": _entity("King's Theatre", "theatre in Edinburgh", 55.941, -3.20),
            "Q2": _entity("King's Theatre", "theatre in Glasgow", 55.864, -4.252),
        },
    )

    verdict = resolve_wikidata_place(
        PlaceCandidate("King's Theatre", "building"),
        COUNTRY_ONLY_GB,
        client=client,  # type: ignore[arg-type]
    )

    assert verdict.status == "ambiguous"
    assert verdict.resolution is None


def test_country_only_resolver_rejects_country_conflict() -> None:
    client = FakeWikidataClient(
        [_search_item("Q1", "Wembley Stadium")],
        {
            "Q1": _entity(
                "Wembley Stadium",
                "stadium in another country",
                40.0,
                -75.0,
                country_id="Q16",
            )
        },
        countries={"Q16": {"claims": {"P297": [{"mainsnak": {"datavalue": {"value": "CA"}}}]}}},
    )

    verdict = resolve_wikidata_place(
        PlaceCandidate("Wembley Stadium", "building"),
        COUNTRY_ONLY_GB,
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


def test_worker_records_generic_rejection_without_wikidata_call(db_session: Session) -> None:
    db_session.add(_rss_row("generic", "Hearing at Magistrates' Court"))
    db_session.commit()
    client = FakeWikidataClient([])

    stats = enrich_news_places(
        db_session,
        limit=10,
        client=client,  # type: ignore[arg-type]
        now=NOW,
    )
    db_session.commit()

    row = db_session.execute(select(EventRow)).scalars().one()
    assert stats["lookups"] == 0
    assert client.calls == []
    assert row.payload["place_resolution"] == "rejected"
    assert row.payload["place_candidate_count"] == 0
    assert row.payload["place_rejected_count"] == 1
    assert row.payload["place_rejections"] == [
        {"name": "Magistrates' Court", "reason": "generic_institution_class"}
    ]
    assert row.payload["geo_basis"] == "term"


def test_worker_keeps_specific_candidate_beside_generic_rejection(
    db_session: Session,
) -> None:
    db_session.add(_country_only_row("mixed", "Royal Albert Hall and City Hall announce closures"))
    db_session.commit()
    client = FakeWikidataClient(
        [_search_item("Q187868", "Royal Albert Hall")],
        {"Q187868": _entity("Royal Albert Hall", "concert hall in London", 51.5009, -0.1774)},
    )

    stats = enrich_news_places(
        db_session,
        limit=10,
        client=client,  # type: ignore[arg-type]
        now=NOW,
    )
    db_session.commit()

    row = db_session.execute(select(EventRow)).scalars().one()
    assert stats["lookups"] == 1
    assert row.payload["place_resolution"] == "resolved"
    assert row.payload["place_wikidata_id"] == "Q187868"
    assert row.payload["place_rejections"] == [
        {"name": "City Hall", "reason": "generic_institution_class"}
    ]


def test_repair_evicts_old_generic_cache_and_withdraws_false_point(
    db_session: Session,
) -> None:
    for key, version in (("a" * 64, "place.wikidata.v1.0"), ("b" * 64, "place.wikidata.v1.2")):
        db_session.add(
            PlaceLookupRow(
                lookup_key=key,
                query_text="Magistrates' Court",
                context_country="GB",
                context_city="Liverpool",
                status="resolved",
                lat=53.3555,
                lon=-2.8984,
                precision="building",
                wikidata_id="Q41957874",
                label="Garston Reading Room",
                description="building in Liverpool",
                checked_at=NOW,
                resolver_version=version,
            )
        )
    db_session.add(
        EventRow(
            source="rss-bbc-uk",
            source_event_id="false-building",
            occurred_at=NOW,
            fetched_at=NOW,
            category="news",
            severity=0.3,
            keywords=[],
            country="GB",
            lat=53.3555,
            lon=-2.8984,
            payload={
                "title": "Manhunt after prisoner escapes from van outside court",
                "summary": (
                    "A prisoner escaped while being taken to Liverpool Magistrates' Court."
                ),
                "city": "Liverpool",
                "geo_basis": "place",
                "news_scope": "local",
                "place_name": "Garston Reading Room",
                "place_wikidata_id": "Q41957874",
                "place_model": "place.wikidata.v1.3",
                "place_resolution": "resolved",
            },
        )
    )
    db_session.commit()

    result = repair_generic_place_names(db_session, now=NOW)
    db_session.commit()

    row = db_session.execute(select(EventRow)).scalars().one()
    assert result == {"cache_rows_evicted": 2, "event_rows_repaired": 1}
    assert db_session.execute(select(PlaceLookupRow)).scalars().all() == []
    assert row.country == "GB"
    assert row.payload["city"] == "Liverpool"
    assert (row.lat, row.lon) == (53.4179, -2.9199)
    assert row.payload["geo_basis"] == "city"
    assert row.payload["place_wikidata_id"] is None
    assert row.payload["place_resolution"] == "pending"
    assert row.payload["place_candidate_count"] == 1
    assert row.payload["place_rejections"] == [
        {"name": "Magistrates' Court", "reason": "generic_institution_class"}
    ]
    assert repair_generic_place_names(db_session, now=NOW) == {
        "cache_rows_evicted": 0,
        "event_rows_repaired": 0,
    }


def test_repair_removes_false_secondary_location_without_losing_valid_primary(
    db_session: Session,
) -> None:
    db_session.add(
        PlaceLookupRow(
            lookup_key="c" * 64,
            query_text="City Hall",
            context_country="GB",
            context_city="",
            status="resolved",
            lat=53.3555,
            lon=-2.8984,
            precision="building",
            wikidata_id="Q41957874",
            label="Garston Reading Room",
            description="building in Liverpool",
            checked_at=NOW,
            resolver_version="place.wikidata.v1.2",
        )
    )
    valid = {
        "name": "Royal Albert Hall",
        "wikidata_id": "Q187868",
        "description": "concert hall in London",
        "lat": 51.5009,
        "lon": -0.1774,
        "precision": "building",
        "checked_at": NOW.isoformat(),
        "model": "place.wikidata.v1.3",
    }
    false = {
        "name": "Garston Reading Room",
        "wikidata_id": "Q41957874",
        "description": "building in Liverpool",
        "lat": 53.3555,
        "lon": -2.8984,
        "precision": "building",
        "checked_at": NOW.isoformat(),
        "model": "place.wikidata.v1.2",
    }
    db_session.add(
        EventRow(
            source="rss-bbc-uk",
            source_event_id="mixed-false-secondary",
            occurred_at=NOW,
            fetched_at=NOW,
            category="news",
            severity=0.3,
            keywords=[],
            country="GB",
            lat=valid["lat"],
            lon=valid["lon"],
            payload={
                "title": "Royal Albert Hall and City Hall issue updates",
                "summary": "",
                "city": "Liverpool",
                "geo_basis": "place",
                "place_name": valid["name"],
                "place_wikidata_id": valid["wikidata_id"],
                "place_description": valid["description"],
                "place_locations": [valid, false],
                "place_model": "place.wikidata.v1.3",
                "place_resolution": "resolved_multiple",
            },
        )
    )
    db_session.commit()

    result = repair_generic_place_names(db_session, now=NOW)
    db_session.commit()

    row = db_session.execute(select(EventRow)).scalars().one()
    assert result == {"cache_rows_evicted": 1, "event_rows_repaired": 1}
    assert (row.lat, row.lon) == (51.5009, -0.1774)
    assert row.payload["geo_basis"] == "place"
    assert row.payload["place_wikidata_id"] == "Q187868"
    assert row.payload["place_locations"] == [valid]
    assert row.payload["place_verified_count"] == 1
    assert row.payload["place_rejected_count"] == 1
    assert row.payload["place_resolution"] == "pending"
    assert row.payload["place_model"] is None


def test_repair_restores_desk_basis_without_inventing_term_evidence(
    db_session: Session,
) -> None:
    db_session.add(
        PlaceLookupRow(
            lookup_key="d" * 64,
            query_text="Magistrates' Court",
            context_country="GB",
            context_city="",
            status="resolved",
            lat=53.3555,
            lon=-2.8984,
            precision="building",
            wikidata_id="Q41957874",
            label="Garston Reading Room",
            description="building in Liverpool",
            checked_at=NOW,
            resolver_version="place.wikidata.v1.2",
        )
    )
    db_session.add(
        EventRow(
            source="rss-bbc-uk",
            source_event_id="desk-fallback",
            occurred_at=NOW,
            fetched_at=NOW,
            category="news",
            severity=0.3,
            keywords=[],
            country="GB",
            lat=53.3555,
            lon=-2.8984,
            payload={
                "title": "Hearing adjourned at Magistrates' Court",
                "summary": "",
                "city": None,
                "geo_basis": "place",
                "place_name": "Garston Reading Room",
                "place_wikidata_id": "Q41957874",
            },
        )
    )
    db_session.commit()

    repair_generic_place_names(db_session, now=NOW)
    db_session.commit()

    row = db_session.execute(select(EventRow)).scalars().one()
    assert row.country == "GB"
    assert (row.lat, row.lon) == (None, None)
    assert row.payload["geo_basis"] == "desk"
    assert row.payload["place_resolution"] == "rejected"


def test_repair_preserves_specific_cache_sharing_generic_point(db_session: Session) -> None:
    point = (40.7127, -74.0060)
    common = {
        "context_country": "US",
        "context_city": "",
        "status": "resolved",
        "lat": point[0],
        "lon": point[1],
        "precision": "building",
        "wikidata_id": "Q543654",
        "label": "New York City Hall",
        "description": "government building in New York City",
        "checked_at": NOW,
        "resolver_version": "place.wikidata.v1.2",
    }
    db_session.add_all(
        [
            PlaceLookupRow(lookup_key="e" * 64, query_text="City Hall", **common),
            PlaceLookupRow(lookup_key="f" * 64, query_text="New York City Hall", **common),
        ]
    )
    location = {
        "name": "New York City Hall",
        "wikidata_id": "Q543654",
        "description": "government building in New York City",
        "lat": point[0],
        "lon": point[1],
        "precision": "building",
        "checked_at": NOW.isoformat(),
        "model": "place.wikidata.v1.2",
    }
    db_session.add(
        EventRow(
            source="rss-cnn-world",
            source_event_id="shared-point",
            occurred_at=NOW,
            fetched_at=NOW,
            category="news",
            severity=0.3,
            keywords=[],
            country="US",
            lat=point[0],
            lon=point[1],
            payload={
                "title": "New York City Hall and City Hall publish updates",
                "summary": "",
                "geo_basis": "place",
                "place_name": location["name"],
                "place_wikidata_id": location["wikidata_id"],
                "place_locations": [location],
            },
        )
    )
    db_session.commit()

    result = repair_generic_place_names(db_session, now=NOW)
    db_session.commit()

    row = db_session.execute(select(EventRow)).scalars().one()
    caches = db_session.execute(select(PlaceLookupRow)).scalars().all()
    assert result == {"cache_rows_evicted": 1, "event_rows_repaired": 0}
    assert [cache.query_text for cache in caches] == ["New York City Hall"]
    assert (row.lat, row.lon) == point
    assert row.payload["geo_basis"] == "place"
    assert row.payload["place_locations"] == [location]


def test_worker_resolves_country_only_story_and_caches_empty_city(db_session: Session) -> None:
    db_session.add(_country_only_row("one", "Wembley Stadium hosts final"))
    db_session.commit()
    client = FakeWikidataClient(
        [_search_item("Q193633", "Wembley Stadium")],
        {
            "Q193633": _entity(
                "Wembley Stadium",
                "football stadium in London, England",
                51.556,
                -0.2796,
            )
        },
    )

    stats = enrich_news_places(
        db_session,
        limit=10,
        client=client,  # type: ignore[arg-type]
        now=NOW,
    )
    db_session.commit()

    row = db_session.execute(select(EventRow)).scalars().one()
    cache = db_session.execute(select(PlaceLookupRow)).scalars().one()
    assert stats["enriched"] == 1
    assert stats["no_context"] == 0
    assert (row.lat, row.lon) == (51.556, -0.2796)
    assert row.payload["geo_basis"] == "place"
    assert cache.context_city == ""


def test_worker_collapses_nested_aliases_that_resolve_to_one_entity(
    db_session: Session,
) -> None:
    db_session.add(
        _country_only_row(
            "nested",
            "IRGC says fighters destroyed at Jordan's Al-Azraq Base",
            country="JO",
            entities=[{"text": "Al-Azraq Base", "label": "FAC"}],
        )
    )
    db_session.commit()
    client = MappedWikidataClient(
        {
            "Jordan's Al-Azraq Base": [_search_item("Q4688334", "Jordan's Al-Azraq Base")],
            "Al-Azraq Base": [_search_item("Q4688334", "Al-Azraq Base")],
        },
        {
            "Q4688334": _entity(
                "Al-Azraq Air Base",
                "air base in Jordan",
                31.8333,
                36.7833,
                country_id="Q810",
            )
        },
        countries={"Q810": {"claims": {"P297": [{"mainsnak": {"datavalue": {"value": "JO"}}}]}}},
    )

    stats = enrich_news_places(
        db_session,
        limit=10,
        client=client,  # type: ignore[arg-type]
        now=NOW,
    )
    db_session.commit()

    row = db_session.execute(select(EventRow)).scalars().one()
    assert stats["multiple"] == 1
    assert stats["verified_locations"] == 1
    assert row.payload["place_resolution"] == "resolved"
    assert row.payload["place_candidate_count"] == 2
    assert row.payload["place_verified_count"] == 1
    assert [item["wikidata_id"] for item in row.payload["place_locations"]] == ["Q4688334"]


def test_worker_preserves_two_independently_verified_places(db_session: Session) -> None:
    db_session.add(
        _rss_row(
            "two-places",
            "Royal Albert Hall and Wembley Stadium announce joint event",
        )
    )
    db_session.commit()
    client = MappedWikidataClient(
        {
            "Royal Albert Hall": [_search_item("Q187868", "Royal Albert Hall")],
            "Wembley Stadium": [_search_item("Q193633", "Wembley Stadium")],
        },
        {
            "Q187868": _entity("Royal Albert Hall", "concert hall in London", 51.5009, -0.1774),
            "Q193633": _entity("Wembley Stadium", "football stadium in London", 51.556, -0.2796),
        },
    )

    stats = enrich_news_places(
        db_session,
        limit=10,
        client=client,  # type: ignore[arg-type]
        now=NOW,
    )
    db_session.commit()

    row = db_session.execute(select(EventRow)).scalars().one()
    locations = row.payload["place_locations"]
    assert stats["multiple"] == 1
    assert stats["verified_locations"] == 2
    assert row.payload["place_resolution"] == "resolved_multiple"
    assert [item["wikidata_id"] for item in locations] == ["Q187868", "Q193633"]
    assert (row.lat, row.lon) == (51.5009, -0.1774)
    assert {
        cache.context_city for cache in db_session.execute(select(PlaceLookupRow)).scalars().all()
    } == {""}


def test_worker_keeps_verified_subset_when_another_place_is_unverified(
    db_session: Session,
) -> None:
    db_session.add(
        _country_only_row(
            "partial",
            "Royal Albert Hall and Wembley Stadium announce joint event",
        )
    )
    db_session.commit()
    client = MappedWikidataClient(
        {
            "Royal Albert Hall": [_search_item("Q187868", "Royal Albert Hall")],
            "Wembley Stadium": [],
        },
        {"Q187868": _entity("Royal Albert Hall", "concert hall in London", 51.5009, -0.1774)},
    )

    stats = enrich_news_places(
        db_session,
        limit=10,
        client=client,  # type: ignore[arg-type]
        now=NOW,
    )
    db_session.commit()

    row = db_session.execute(select(EventRow)).scalars().one()
    assert stats["partial"] == 1
    assert row.payload["place_resolution"] == "resolved_partial"
    assert row.payload["place_candidate_count"] == 2
    assert row.payload["place_verified_count"] == 1
    assert [item["wikidata_id"] for item in row.payload["place_locations"]] == ["Q187868"]


def test_worker_leaves_multi_place_row_pending_when_lookup_budget_runs_out(
    db_session: Session,
) -> None:
    db_session.add(
        _country_only_row(
            "budgeted",
            "Royal Albert Hall and Wembley Stadium announce joint event",
        )
    )
    db_session.commit()
    first_client = MappedWikidataClient(
        {"Royal Albert Hall": [_search_item("Q187868", "Royal Albert Hall")]},
        {"Q187868": _entity("Royal Albert Hall", "concert hall in London", 51.5009, -0.1774)},
    )

    first = enrich_news_places(
        db_session,
        limit=1,
        client=first_client,  # type: ignore[arg-type]
        now=NOW,
    )
    db_session.commit()
    row = db_session.execute(select(EventRow)).scalars().one()
    assert first["lookups"] == 1
    assert row.payload["place_resolution"] == "pending"
    assert row.payload["place_model"] is None
    assert row.payload["place_verified_count"] == 1

    second_client = MappedWikidataClient(
        {"Wembley Stadium": [_search_item("Q193633", "Wembley Stadium")]},
        {"Q193633": _entity("Wembley Stadium", "football stadium in London", 51.556, -0.2796)},
    )
    second = enrich_news_places(
        db_session,
        limit=1,
        client=second_client,  # type: ignore[arg-type]
        now=NOW + timedelta(minutes=30),
    )
    db_session.commit()
    db_session.expire_all()
    row = db_session.execute(select(EventRow)).scalars().one()
    assert second["cache_hits"] == 1
    assert second["lookups"] == 1
    assert row.payload["place_resolution"] == "resolved_multiple"
    assert row.payload["place_verified_count"] == 2


def test_worker_preserves_v11_english_cache_after_language_rules_change(
    db_session: Session,
) -> None:
    cache = _resolved_country_cache("Royal Albert Hall", "Q187868", 51.5009, -0.1774)
    old_material = "|".join(("place.wikidata.v1.1", "royal albert hall", "GB", ""))
    cache.lookup_key = hashlib.sha256(old_material.encode()).hexdigest()
    cache.resolver_version = "place.wikidata.v1.1"
    db_session.add_all([cache, _country_only_row("reuse", "Royal Albert Hall announces event")])
    db_session.commit()
    client = FailingWikidataClient()

    stats = enrich_news_places(
        db_session,
        limit=10,
        client=client,  # type: ignore[arg-type]
        now=NOW,
    )
    db_session.commit()

    row = db_session.execute(select(EventRow)).scalars().one()
    assert stats["cache_hits"] == 1
    assert stats["lookups"] == 0
    assert stats["errors"] == 0
    assert row.payload["place_model"] == PLACE_METHOD_VERSION
    assert row.payload["place_locations"][0]["model"] == "place.wikidata.v1.1"
    assert len(db_session.execute(select(PlaceLookupRow)).scalars().all()) == 1


def test_multi_place_cache_survives_refresh_then_withdraws(db_session: Session) -> None:
    db_session.add_all(
        [
            _resolved_country_cache("Royal Albert Hall", "Q187868", 51.5009, -0.1774),
            _resolved_country_cache("Wembley Stadium", "Q193633", 51.556, -0.2796),
        ]
    )
    db_session.commit()

    upsert_events(
        [
            _country_only_event(
                "multi-story",
                "Royal Albert Hall and Wembley Stadium announce joint event",
            )
        ],
        db_session,
    )
    db_session.commit()
    row = db_session.execute(select(EventRow)).scalars().one()
    assert row.payload["place_resolution"] == "resolved_multiple"
    assert len(row.payload["place_locations"]) == 2
    assert (row.lat, row.lon) == (51.5009, -0.1774)

    upsert_events(
        [_country_only_event("multi-story", "Britain publishes venue guidance")],
        db_session,
    )
    db_session.commit()
    db_session.expire_all()
    row = db_session.execute(select(EventRow)).scalars().one()
    assert (row.lat, row.lon) == (None, None)
    assert row.payload.get("place_locations") is None
    assert row.payload["geo_basis"] == "term"


def test_country_only_cached_place_survives_refresh_then_withdraws(
    db_session: Session,
) -> None:
    db_session.add(_country_only_resolved_cache())
    db_session.commit()

    upsert_events([_country_only_event("story", "Wembley Stadium hosts final")], db_session)
    db_session.commit()
    row = db_session.execute(select(EventRow)).scalars().one()
    assert (row.lat, row.lon) == (51.556, -0.2796)
    assert row.payload["geo_basis"] == "place"

    upsert_events([_country_only_event("story", "Britain publishes sports budget")], db_session)
    db_session.commit()
    db_session.expire_all()
    row = db_session.execute(select(EventRow)).scalars().one()
    assert (row.lat, row.lon) == (None, None)
    assert row.payload["geo_basis"] == "term"
    assert row.payload.get("place_wikidata_id") is None


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
