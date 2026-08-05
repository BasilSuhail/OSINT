"""Which GDELT rows get a headline fetched, and what a failure costs (#788).

The selection rules matter as much as the fetch. A beat that keeps asking a
dead link never reaches the live rows behind it, and a beat that fetches
country-precision rows spends requests on markers nobody can click.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db_models import Base, EventRow
from app.enrichment import gdelt_titles
from app.enrichment.article_title import TitleResult

NOW = datetime(2026, 8, 4, 21, 0, tzinfo=UTC)


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _add(session: Session, **payload: Any) -> int:
    base: dict[str, Any] = {
        "geo_precision": "city",
        "source_url": "https://example.com/story",
        "action_label": "Coerce",
    }
    base.update(payload)
    minutes = int(base.pop("_age_minutes", 0))
    row = EventRow(
        source=str(base.pop("_source", "gdelt")),
        source_event_id=f"e{id(base)}{minutes}",
        occurred_at=NOW - timedelta(minutes=minutes),
        fetched_at=NOW,
        category="geopolitical",
        payload=base,
    )
    session.add(row)
    session.flush()
    return row.id


class TestPendingIds:
    def test_a_mapped_row_with_no_title_is_pending(self, session: Session) -> None:
        wanted = _add(session)
        assert gdelt_titles.pending_ids(session) == [wanted]

    def test_a_row_that_already_has_one_is_left_alone(self, session: Session) -> None:
        _add(session, title="Two villages evacuated as wildfire jumps the ridge")
        assert gdelt_titles.pending_ids(session) == []

    def test_country_precision_rows_are_never_drawn_so_never_fetched(
        self, session: Session
    ) -> None:
        """A country-level coordinate means 'somewhere in Russia' and is not
        pinned (#727). A headline for it is a request spent on nothing."""
        _add(session, geo_precision="country")
        assert gdelt_titles.pending_ids(session) == []

    def test_a_timestamp_where_a_url_belongs_is_skipped(self, session: Session) -> None:
        """Rows stored before #733 carry a 14-digit DATEADDED in source_url."""
        _add(session, source_url="20260803094500")
        assert gdelt_titles.pending_ids(session) == []

    def test_a_row_that_gave_up_is_not_asked_again(self, session: Session) -> None:
        _add(session, title_status="gave-up", title_attempts=3)
        assert gdelt_titles.pending_ids(session) == []

    def test_attempts_are_capped(self, session: Session) -> None:
        _add(session, title_attempts=gdelt_titles.MAX_ATTEMPTS)
        assert gdelt_titles.pending_ids(session) == []

    def test_only_gdelt(self, session: Session) -> None:
        _add(session, _source="rss-bbc")
        assert gdelt_titles.pending_ids(session) == []

    def test_newest_first(self, session: Session) -> None:
        """The reader is looking at now. An older row may age out of the
        retention window before they ever scroll to it."""
        old = _add(session, _age_minutes=600)
        new = _add(session, _age_minutes=1)
        assert gdelt_titles.pending_ids(session) == [new, old]

    def test_the_batch_is_bounded(self, session: Session) -> None:
        for i in range(5):
            _add(session, _age_minutes=i)
        assert len(gdelt_titles.pending_ids(session, limit=2)) == 2


class TestEnrichTitles:
    def _stub(self, monkeypatch: pytest.MonkeyPatch, result: TitleResult) -> None:
        monkeypatch.setattr(
            gdelt_titles,
            "fetch_title",
            lambda url, client=None: result,
        )

    def test_a_found_headline_lands_on_the_row(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        row_id = _add(session)
        self._stub(monkeypatch, TitleResult("Villages evacuated as wildfire spreads", "ok", False))
        stats = gdelt_titles.enrich_titles(session)
        assert stats == {"considered": 1, "titled": 1, "failed": 0, "ran_out_of_time": 0}
        payload = session.get(EventRow, row_id).payload
        assert payload["title"] == "Villages evacuated as wildfire spreads"
        assert payload["title_source"] == "article"
        #: The CAMEO label stays: it is a real machine field, and the detail
        #: card shows it as one. It just no longer stands in for a headline.
        assert payload["action_label"] == "Coerce"

    def test_a_retryable_failure_leaves_the_row_pending(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _add(session)
        self._stub(monkeypatch, TitleResult(None, "timeout", True))
        gdelt_titles.enrich_titles(session)
        assert len(gdelt_titles.pending_ids(session)) == 1

    def test_a_dead_link_is_given_up_on_immediately(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """404 is not a temporary condition. Asking again every five minutes
        for thirty days would starve the rows behind it."""
        _add(session)
        self._stub(monkeypatch, TitleResult(None, "http-404", False))
        gdelt_titles.enrich_titles(session)
        assert gdelt_titles.pending_ids(session) == []

    def test_repeated_timeouts_eventually_give_up(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _add(session)
        self._stub(monkeypatch, TitleResult(None, "timeout", True))
        for _ in range(gdelt_titles.MAX_ATTEMPTS):
            gdelt_titles.enrich_titles(session)
        assert gdelt_titles.pending_ids(session) == []

    def test_one_dead_link_does_not_end_the_batch(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = _add(session, _age_minutes=1)
        second = _add(session, _age_minutes=2)
        calls: list[str] = []

        def fetch(url: str, client: httpx.Client | None = None) -> TitleResult:
            calls.append(url)
            if len(calls) == 1:
                return TitleResult(None, "http-500", True)
            return TitleResult("The second article's real headline", "ok", False)

        monkeypatch.setattr(gdelt_titles, "fetch_title", fetch)
        stats = gdelt_titles.enrich_titles(session)
        assert stats == {"considered": 2, "titled": 1, "failed": 1, "ran_out_of_time": 0}
        assert session.get(EventRow, first).payload.get("title") is None
        assert (
            session.get(EventRow, second).payload["title"] == "The second article's real headline"
        )

    def test_a_slow_batch_stops_before_the_next_beat_fires(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sixty rows that each time out would run past the five-minute beat,
        the next run would select the same rows — the attempt counter is only
        written at the end — and every row in the overlap would be fetched
        twice. The clock stops that however slow the batch is."""
        for i in range(4):
            _add(session, _age_minutes=i)
        clock = iter([0.0, 0.0, 1.0, 99.0])
        monkeypatch.setattr(gdelt_titles, "monotonic", lambda: next(clock))
        self._stub(monkeypatch, TitleResult("A real headline from the article", "ok", False))

        stats = gdelt_titles.enrich_titles(session, budget_s=10.0)

        assert stats["considered"] == 2
        assert stats["ran_out_of_time"] == 2
        #: The rows never reached carry no attempt, so the next run takes them
        #: first rather than skipping them.
        assert len(gdelt_titles.pending_ids(session)) == 2

    def test_nothing_to_do_costs_no_requests(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fetch(url: str, client: httpx.Client | None = None) -> TitleResult:  # pragma: no cover
            raise AssertionError("must not fetch")

        monkeypatch.setattr(gdelt_titles, "fetch_title", fetch)
        assert gdelt_titles.enrich_titles(session) == {
            "considered": 0,
            "titled": 0,
            "failed": 0,
            "ran_out_of_time": 0,
        }
