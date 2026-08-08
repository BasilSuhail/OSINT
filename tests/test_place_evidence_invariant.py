"""A row may not claim a building it cannot name (#756).

The row that prompted this said `geo_basis='place'` and carried a coordinate,
with `place_name`, `place_wikidata_id`, `place_model` all null and
`place_verified_count` zero. Its point was correct — it really was King's
Theatre — and nothing in the row could show that. A correct point and a wrong
one looked identical:

- that row was right and unexplainable
- the Garston row (#755) was wrong and, until read against the lookup cache,
  equally unexplainable

No writer produces that state today; a migration left it behind. The state is
still *representable*, which is the actual defect — nothing rejects it on the
way in and nothing reports it once it exists. Both are fixed here.

`geo_basis='place'` is a claim about evidence, so it must be backed by the
evidence it names. A row that cannot back it keeps its country and loses its
point, exactly as an ambiguous resolution does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.audit import checks, run
from app.db_models import Base, EventRow
from app.enrichment.place import place_evidence_holds, without_unbacked_place

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        yield s


def _backed() -> dict:
    return {
        "title": "King's Theatre in Edinburgh re-opens after £41m refurbishment",
        "geo_basis": "place",
        "place_name": "King's Theatre",
        "place_wikidata_id": "Q6411122",
        "place_verified_count": 1,
        "place_locations": [{"name": "King's Theatre", "lat": 55.94, "lon": -3.2}],
    }


def _bare() -> dict:
    """The observed state: the basis survived, the evidence did not."""
    return {
        "title": "King's Theatre in Edinburgh re-opens after £41m refurbishment",
        "geo_basis": "place",
        "place_name": None,
        "place_wikidata_id": None,
        "place_model": None,
        "place_verified_count": 0,
        "place_locations": [],
    }


class TestTheInvariant:
    def test_a_backed_claim_holds(self) -> None:
        assert place_evidence_holds(_backed())

    def test_a_bare_claim_does_not(self) -> None:
        assert not place_evidence_holds(_bare())

    def test_a_claim_with_a_count_but_no_locations_does_not(self) -> None:
        """The count is a summary of the locations, so it cannot outvote them."""
        payload = _backed() | {"place_locations": []}
        assert not place_evidence_holds(payload)

    def test_other_bases_are_not_asked_for_place_evidence(self) -> None:
        for basis in ("city", "region", "term", "desk", "domestic", "ambiguous", "none"):
            assert place_evidence_holds({"geo_basis": basis}), basis


class TestDemotion:
    def test_an_unbacked_claim_loses_the_basis(self) -> None:
        payload = without_unbacked_place(_bare())
        assert payload["geo_basis"] != "place"
        assert payload.get("place_demoted") == "no_verified_location"

    def test_a_backed_claim_is_returned_unchanged(self) -> None:
        payload = _backed()
        assert without_unbacked_place(payload) == payload

    def test_the_country_survives_the_demotion(self) -> None:
        """Losing the point is not losing the story: it is still British news
        and must still be reachable by clicking the country."""
        payload = without_unbacked_place(_bare() | {"country": "GB"})
        assert payload["country"] == "GB"


class TestTheAuditReportsIt:
    def _row(self, payload: dict, *, n: int = 1) -> EventRow:
        return EventRow(
            source="rss-edinburgh-live",
            source_event_id=f"row-{n}",
            occurred_at=NOW - timedelta(hours=1),
            fetched_at=NOW,
            category="news",
            keywords=[],
            lat=55.94,
            lon=-3.2,
            payload=payload,
        )

    def test_a_bare_claim_becomes_a_finding(self, session) -> None:
        session.add(self._row(_bare()))
        session.commit()
        findings = run.audit(session, now=NOW)
        place = [f for f in findings if f.check == "place_evidence"]
        assert len(place) == 1
        assert "1" in place[0].detail

    def test_a_backed_claim_produces_no_finding(self, session) -> None:
        session.add(self._row(_backed()))
        session.commit()
        assert [f for f in run.audit(session, now=NOW) if f.check == "place_evidence"] == []

    def test_the_finding_names_the_source_it_came_from(self, session) -> None:
        session.add(self._row(_bare(), n=1))
        session.add(self._row(_bare(), n=2))
        session.commit()
        finding = next(f for f in run.audit(session, now=NOW) if f.check == "place_evidence")
        assert finding.source == "rss-edinburgh-live"
        assert "2" in finding.detail

    def test_it_is_a_real_check_not_a_stats_artefact(self) -> None:
        assert "place_evidence" in {f for f in dir(checks) if "place" in f} or hasattr(
            checks, "check_place_evidence"
        )
