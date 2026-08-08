"""A file that is not published yet is not a dead resource (#808).

GDELT's export URL names the fifteen-minute window it covers, so it is a
different object every quarter hour. On 2026-08-08 `lastupdate.txt` advertised
`20260808001500.export.CSV.zip` before the object was readable, the fetch
landed in that gap, and a 404 parked the largest feed in the system for an
hour. Fetched by hand afterwards the same URL answered 200.

Nine such 404s landed in twenty-one days. The classifier could not tell them
from `rss-arab-news` answering 403 forever, because nothing recorded which
kind of URL a fetcher uses.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db_models import Base, SourceQuarantineRow
from app.ingest import quarantine
from app.sources.gdelt_fetcher import GdeltFetcher
from app.sources.rss_news_fetcher import RssNewsFetcher


@pytest.fixture
def session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        yield s


def _http_error(status: int) -> httpx.HTTPStatusError:
    response = httpx.Response(
        status,
        request=httpx.Request(
            "GET", "http://data.gdeltproject.org/gdeltv2/20260808001500.export.CSV.zip"
        ),
    )
    return httpx.HTTPStatusError("boom", request=response.request, response=response)


class TestClassification:
    @pytest.mark.parametrize("status", [404, 410])
    def test_a_missing_time_addressed_file_is_about_the_moment(self, status) -> None:
        assert quarantine.classify(_http_error(status), stable_urls=False) is None

    @pytest.mark.parametrize("status", [404, 410])
    def test_the_same_status_on_a_stable_url_stays_permanent(self, status) -> None:
        # #567 must not regress: arabnews.com/rss.xml answering 404 is a fact
        # that will still be true in an hour.
        assert quarantine.classify(_http_error(status)) == "permanent"

    @pytest.mark.parametrize("status", [401, 403])
    def test_being_forbidden_is_about_the_resource_however_it_is_addressed(self, status) -> None:
        assert quarantine.classify(_http_error(status), stable_urls=False) == "permanent"

    def test_throttling_is_unaffected_by_addressing(self) -> None:
        assert quarantine.classify(_http_error(429), stable_urls=False) == "throttled"


class TestRecording:
    def test_a_late_file_leaves_no_quarantine_row(self, session) -> None:
        row = quarantine.record_failure(
            session, source="gdelt", exc=_http_error(404), stable_urls=False
        )
        session.flush()
        assert row is None
        assert session.execute(select(SourceQuarantineRow)).scalars().all() == []

    def test_a_dead_feed_is_still_parked(self, session) -> None:
        row = quarantine.record_failure(session, source="rss-arab-news", exc=_http_error(403))
        session.flush()
        assert row is not None
        assert row.kind == "permanent"


class TestTaskWiring:
    """The declaration is worthless if the task path does not read it."""

    def _install(self, monkeypatch, *, stable_urls: bool, boom) -> None:
        class _Fetcher:
            def __init__(self) -> None:
                self.stable_urls = stable_urls

            def fetch(self):
                raise boom

        import app.fetcher_registry as registry

        monkeypatch.setattr(registry, "get_fetcher", lambda _n: _Fetcher())

    def _scope(self, session):
        from contextlib import contextmanager

        @contextmanager
        def scope():
            yield session

        return scope

    def test_gdelt_404_raises_for_celery_instead_of_parking_the_feed(
        self, monkeypatch, session
    ) -> None:
        from app import tasks

        monkeypatch.setattr(tasks, "session_scope", self._scope(session))
        self._install(monkeypatch, stable_urls=False, boom=_http_error(404))

        with pytest.raises(httpx.HTTPStatusError):
            tasks._run_fetcher_body("gdelt")
        assert session.execute(select(SourceQuarantineRow)).scalars().all() == []

    def test_a_stable_source_404_still_parks(self, monkeypatch, session) -> None:
        from app import tasks

        monkeypatch.setattr(tasks, "session_scope", self._scope(session))
        self._install(monkeypatch, stable_urls=True, boom=_http_error(404))

        result = tasks._run_fetcher_body("rss-nation-kenya")
        assert result["quarantined"] is True


class TestFetcherDeclaration:
    def test_gdelt_declares_its_urls_unstable(self) -> None:
        assert GdeltFetcher.stable_urls is False

    def test_everything_else_defaults_to_stable(self) -> None:
        # The safe default: a fetcher that has not thought about this keeps
        # the #567 behaviour, because most URLs really are the same resource
        # every time they are fetched.
        assert RssNewsFetcher.stable_urls is True
