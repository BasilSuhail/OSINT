"""Quarantining feeds that cannot succeed (#567)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db_models import Base, SourceQuarantineRow
from app.ingest import quarantine


@pytest.fixture
def session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        yield s


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; Postgres stores them tz-aware."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _http_error(status: int, *, retry_after: str | None = None) -> httpx.HTTPStatusError:
    headers = {"retry-after": retry_after} if retry_after else {}
    response = httpx.Response(
        status, headers=headers, request=httpx.Request("GET", "https://example.com/rss.xml")
    )
    return httpx.HTTPStatusError("boom", request=response.request, response=response)


class TestClassification:
    @pytest.mark.parametrize("status", [401, 403, 404, 410])
    def test_a_statement_about_the_resource_is_permanent(self, status) -> None:
        # 403 and 404 describe the URL, not the moment. Retrying them on the
        # same schedule as a timeout is what produced 420 rows for one feed.
        assert quarantine.classify(_http_error(status)) == "permanent"

    def test_rate_limiting_is_a_real_later_not_a_never(self) -> None:
        assert quarantine.classify(_http_error(429)) == "throttled"

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_server_faults_stay_transient(self, status) -> None:
        assert quarantine.classify(_http_error(status)) is None

    def test_network_faults_stay_transient(self) -> None:
        assert quarantine.classify(httpx.ConnectTimeout("timed out")) is None
        assert quarantine.classify(RuntimeError("something else")) is None


class TestBackoff:
    def test_a_permanent_failure_escalates_and_caps(self) -> None:
        steps = [quarantine.backoff_for("permanent", n) for n in range(1, 8)]
        assert steps == sorted(steps), "backoff must never shrink as failures repeat"
        assert steps[0] >= timedelta(hours=1)
        assert steps[-1] == quarantine.MAX_BACKOFF

    def test_throttling_backs_off_less_than_a_dead_url(self) -> None:
        assert quarantine.backoff_for("throttled", 1) < quarantine.backoff_for("permanent", 1)


class TestQuarantineLifecycle:
    def test_a_permanent_failure_quarantines_the_source(self, session) -> None:
        now = datetime.now(UTC)
        quarantine.record_failure(session, source="rss-arab-news", exc=_http_error(403), now=now)
        row = session.execute(select(SourceQuarantineRow)).scalar_one()
        assert row.source == "rss-arab-news"
        assert row.kind == "permanent"
        assert row.http_status == 403
        assert _aware(row.retry_after) > now
        assert row.consecutive_failures == 1

    def test_repeated_failures_push_the_retry_further_out(self, session) -> None:
        now = datetime.now(UTC)
        quarantine.record_failure(session, source="rss-arab-news", exc=_http_error(403), now=now)
        first = session.execute(select(SourceQuarantineRow)).scalar_one().retry_after
        quarantine.record_failure(session, source="rss-arab-news", exc=_http_error(403), now=now)
        row = session.execute(select(SourceQuarantineRow)).scalar_one()
        assert row.consecutive_failures == 2
        assert _aware(row.retry_after) > _aware(first)

    def test_the_row_records_what_went_wrong_and_since_when(self, session) -> None:
        # "We must know what the failures are and when it stops."
        now = datetime.now(UTC)
        quarantine.record_failure(session, source="rss-arab-news", exc=_http_error(403), now=now)
        row = session.execute(select(SourceQuarantineRow)).scalar_one()
        assert _aware(row.first_failed_at) == now
        assert "403" in row.detail

    def test_a_transient_failure_never_quarantines(self, session) -> None:
        quarantine.record_failure(
            session, source="rss-agencia-brasil", exc=httpx.ConnectTimeout("nope")
        )
        assert session.execute(select(SourceQuarantineRow)).first() is None

    def test_success_clears_the_quarantine_immediately(self, session) -> None:
        quarantine.record_failure(session, source="rss-arab-news", exc=_http_error(403))
        quarantine.record_success(session, source="rss-arab-news")
        assert session.execute(select(SourceQuarantineRow)).first() is None

    def test_success_on_a_healthy_source_is_a_no_op(self, session) -> None:
        quarantine.record_success(session, source="usgs-quake")
        assert session.execute(select(SourceQuarantineRow)).first() is None


class TestSkipDecision:
    def test_a_quarantined_source_is_skipped_until_its_retry_time(self, session) -> None:
        now = datetime.now(UTC)
        quarantine.record_failure(session, source="rss-arab-news", exc=_http_error(403), now=now)
        reason = quarantine.skip_reason(session, "rss-arab-news", now=now + timedelta(minutes=5))
        assert reason is not None
        assert "403" in reason

    def test_the_source_is_tried_again_once_the_window_passes(self, session) -> None:
        now = datetime.now(UTC)
        quarantine.record_failure(session, source="rss-arab-news", exc=_http_error(403), now=now)
        later = now + quarantine.MAX_BACKOFF + timedelta(hours=1)
        assert quarantine.skip_reason(session, "rss-arab-news", now=later) is None

    def test_an_unquarantined_source_is_never_skipped(self, session) -> None:
        assert quarantine.skip_reason(session, "usgs-quake") is None

    def test_retry_after_header_is_honoured_when_longer(self, session) -> None:
        now = datetime.now(UTC)
        quarantine.record_failure(
            session,
            source="uk-police",
            exc=_http_error(429, retry_after="86400"),
            now=now,
        )
        row = session.execute(select(SourceQuarantineRow)).scalar_one()
        assert _aware(row.retry_after) >= now + timedelta(hours=23)


class TestFetcherWiring:
    """`_run_fetcher_body` must skip a rested source and never retry-storm."""

    def test_a_permanent_failure_returns_instead_of_raising(self, monkeypatch, session) -> None:
        # Raising would let autoretry_for=(Exception,) spend five more requests
        # on a URL that just answered 403 — the 420-requests-a-week bug.
        from app import tasks

        monkeypatch.setattr(tasks, "session_scope", _scope(session))
        monkeypatch.setattr(tasks, "upsert_events", lambda events, session: 0, raising=False)
        _install_fetcher(monkeypatch, "rss-arab-news", boom=_http_error(403))

        result = tasks._run_fetcher_body("rss-arab-news")
        assert result["quarantined"] is True
        assert "403" in result["reason"]

    def test_a_transient_failure_still_raises_for_celery_to_retry(
        self, monkeypatch, session
    ) -> None:
        from app import tasks

        monkeypatch.setattr(tasks, "session_scope", _scope(session))
        _install_fetcher(monkeypatch, "rss-agencia-brasil", boom=httpx.ConnectTimeout("nope"))

        with pytest.raises(httpx.ConnectTimeout):
            tasks._run_fetcher_body("rss-agencia-brasil")

    def test_a_quarantined_source_is_not_fetched_at_all(self, monkeypatch, session) -> None:
        from app import tasks

        monkeypatch.setattr(tasks, "session_scope", _scope(session))
        quarantine.record_failure(session, source="rss-arab-news", exc=_http_error(403))
        session.commit()
        calls: list[str] = []
        _install_fetcher(monkeypatch, "rss-arab-news", boom=None, on_call=calls.append)

        result = tasks._run_fetcher_body("rss-arab-news")
        assert result["skipped"] is True
        assert calls == [], "a rested source was fetched anyway"

    def test_a_success_releases_the_quarantine(self, monkeypatch, session) -> None:
        from app import tasks

        monkeypatch.setattr(tasks, "session_scope", _scope(session))
        monkeypatch.setattr(tasks, "upsert_events", lambda events, session: 0)
        quarantine.record_failure(session, source="rss-arab-news", exc=_http_error(403))
        session.execute(
            SourceQuarantineRow.__table__.update().values(
                retry_after=datetime.now(UTC) - timedelta(hours=1)
            )
        )
        session.commit()
        _install_fetcher(monkeypatch, "rss-arab-news", boom=None)

        tasks._run_fetcher_body("rss-arab-news")
        assert session.execute(select(SourceQuarantineRow)).first() is None


def _scope(session):
    """A session_scope stand-in that hands back the test's session."""
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        yield session
        session.flush()

    return _cm


def _install_fetcher(monkeypatch, name: str, *, boom, on_call=None) -> None:
    class _Fetcher:
        def fetch(self):
            if on_call is not None:
                on_call(name)
            if boom is not None:
                raise boom
            return []

    import app.fetcher_registry as registry

    monkeypatch.setattr(registry, "get_fetcher", lambda _n: _Fetcher())
