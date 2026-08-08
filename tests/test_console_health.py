"""Can this console be trusted right now? (#828)

Every container reported healthy while UK Police stored zero rows for its
whole existence (#765) and while GDELT sat parked over a file published two
minutes late (#808). "Up" was never the question.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import console_health
from app.api import app, get_session
from app.db_models import AuditFindingRow, AuditRunRow, EventRow, SourceQuarantineRow

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def _event(source: str, *, minutes_ago: int = 5, payload: dict | None = None, positioned=True):
    return EventRow(
        source=source,
        source_event_id=f"{source}-{minutes_ago}-{positioned}",
        occurred_at=NOW - timedelta(minutes=minutes_ago),
        fetched_at=NOW - timedelta(minutes=minutes_ago),
        category="geopolitical",
        keywords=[],
        lat=55.9 if positioned else None,
        lon=-3.2 if positioned else None,
        payload=payload or {"title": "A story", "geo_basis": "city", "geo_precision": "city"},
    )


class TestSourceClasses:
    def test_each_family_is_named(self) -> None:
        assert console_health.class_of("rss-edinburgh-live") == "news"
        assert console_health.class_of("gdelt") == "machine-coded"
        assert console_health.class_of("nasa-firms") == "hazard"
        assert console_health.class_of("abuse-ch-urlhaus") == "cyber"
        assert console_health.class_of("uk-police") == "crime"

    def test_an_unclaimed_source_is_visible_rather_than_folded_in(self) -> None:
        """A source no class knows about is one nobody decided how to read.
        Hiding it inside a neighbour's count is how it stays undecided."""
        assert console_health.class_of("some-new-feed") == "other"


class TestComposition:
    def test_classes_are_counted_separately(self, db_session) -> None:
        db_session.add_all(
            [_event("gdelt", minutes_ago=i) for i in range(7)]
            + [_event("rss-bbc-uk", minutes_ago=i) for i in range(3)]
        )
        db_session.commit()
        health = console_health.build(db_session, now=NOW)
        by_name = {c.name: c for c in health.composition}
        assert by_name["machine-coded"].rows == 7
        assert by_name["news"].rows == 3
        assert by_name["machine-coded"].share == 0.7

    def test_a_class_reports_how_stale_its_newest_row_is(self, db_session) -> None:
        """A wire and a monthly archive are both healthy at very different
        ages, so freshness is per class or it is meaningless."""
        db_session.add_all(
            [_event("rss-bbc-uk", minutes_ago=9), _event("uk-police", minutes_ago=4000)]
        )
        db_session.commit()
        by_name = {c.name: c for c in console_health.build(db_session, now=NOW).composition}
        assert by_name["news"].newest_age_minutes == 9
        assert by_name["crime"].newest_age_minutes == 4000

    def test_an_empty_corpus_does_not_divide_by_zero(self, db_session) -> None:
        assert console_health.build(db_session, now=NOW).composition == []

    def test_a_lagged_archive_still_counts_as_arriving(self, db_session) -> None:
        """UK Police publishes two months in arrears (#765). Counting
        composition on occurrence reports it as contributing nothing, which is
        precisely how it looked healthy while storing nothing."""
        row = _event("uk-police", minutes_ago=5)
        row.occurred_at = NOW - timedelta(days=68)
        db_session.add(row)
        db_session.commit()
        by_name = {c.name: c for c in console_health.build(db_session, now=NOW).composition}
        assert by_name["crime"].rows == 1
        assert by_name["crime"].newest_age_minutes == 68 * 24 * 60


class TestPrecisionMix:
    def test_it_says_what_the_coordinates_claim(self, db_session) -> None:
        db_session.add_all(
            [
                _event(
                    "rss-a",
                    minutes_ago=1,
                    payload={"title": "x", "geo_basis": "place", "geo_precision": "building"},
                ),
                _event(
                    "rss-b",
                    minutes_ago=2,
                    payload={"title": "x", "geo_basis": "city", "geo_precision": "city"},
                ),
                _event("rss-c", minutes_ago=3, payload={"title": "x", "geo_basis": "term"}),
            ]
        )
        db_session.commit()
        assert console_health.build(db_session, now=NOW).precision == {
            "exact": 1,
            "city": 1,
            "country": 1,
        }

    def test_unpositioned_rows_are_not_sampled(self, db_session) -> None:
        """A row with no coordinate makes no claim, and counting it as one
        would put a number on an absence."""
        db_session.add(_event("rss-a", positioned=False))
        db_session.commit()
        assert console_health.build(db_session, now=NOW).precision == {}


class TestRestedSources:
    def test_a_quarantined_source_says_why_and_until_when(self, db_session) -> None:
        db_session.add(
            SourceQuarantineRow(
                source="rss-arab-news",
                kind="permanent",
                http_status=403,
                detail="HTTP 403: Forbidden",
                consecutive_failures=6,
                first_failed_at=NOW - timedelta(days=1),
                last_failed_at=NOW,
                retry_after=NOW + timedelta(days=1),
            )
        )
        db_session.commit()
        rested = console_health.build(db_session, now=NOW).rested
        assert [r.source for r in rested] == ["rss-arab-news"]
        assert rested[0].http_status == 403
        assert "403" in rested[0].detail


class TestAuditSummary:
    def test_it_reports_the_last_stored_run(self, db_session) -> None:
        run = AuditRunRow(
            started_at=NOW - timedelta(hours=2),
            finished_at=NOW - timedelta(hours=2),
            sources_measured=58,
            findings_total=3,
        )
        db_session.add(run)
        db_session.flush()
        db_session.add_all(
            [
                AuditFindingRow(
                    run_id=run.id, source="a", check_name="country_coverage", detail="x"
                ),
                AuditFindingRow(
                    run_id=run.id, source="b", check_name="country_coverage", detail="x"
                ),
                AuditFindingRow(run_id=run.id, source="c", check_name="severity_shape", detail="x"),
            ]
        )
        db_session.commit()
        audit = console_health.build(db_session, now=NOW).audit
        assert audit["findings_total"] == 3
        assert audit["by_check"] == {"country_coverage": 2, "severity_shape": 1}
        assert audit["ran_at"] is not None

    def test_never_having_run_is_not_the_same_as_clean(self, db_session) -> None:
        """The failure shape this project has hit repeatedly: an absent
        measurement reading as a passing one."""
        audit = console_health.build(db_session, now=NOW).audit
        assert audit["ran_at"] is None
        assert audit["findings_total"] == 0


class TestThroughTheApi:
    def test_the_endpoint_serves_the_whole_answer(self, db_session) -> None:
        db_session.add(_event("gdelt"))
        db_session.commit()
        app.dependency_overrides[get_session] = lambda: db_session
        body = TestClient(app).get("/console/health").json()
        assert set(body) == {
            "generated_at",
            "silent",
            "rested",
            "audit",
            "composition",
            "precision",
        }
        assert body["composition"][0]["name"] == "machine-coded"

    def test_an_empty_corpus_reports_every_source_as_never_heard_from(self, db_session) -> None:
        """An empty database is not a healthy one, and the panel must not
        flatter it. A source with no successful fetch on record reports None
        rather than a number, because "never" and "two days ago" are different
        problems with different fixes."""
        app.dependency_overrides[get_session] = lambda: db_session
        body = TestClient(app).get("/console/health").json()
        assert body["silent"], "an empty corpus reported nothing silent"
        assert body["silent"][0]["minutes_silent"] is None
        assert body["rested"] == []
        assert body["generated_at"]
