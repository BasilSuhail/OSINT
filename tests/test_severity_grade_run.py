"""The regrade batch runner — resumable, incremental (#596).

A full news regrade is ~13h of model calls. It must never be one transaction
that saves nothing when interrupted, and a re-run must pick up where a killed
one stopped rather than starting over.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db_models import EventRow
from app.severity import grade_run, news


def _news_row(session, i, *, method=None):
    payload = {"title": f"headline {i}"}
    if method:
        payload["severity_method"] = method
    session.add(
        EventRow(
            source="rss-test",
            source_event_id=f"n{i}",
            occurred_at=datetime(2026, 7, 1, tzinfo=UTC) - timedelta(minutes=i),
            fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
            category="news",
            severity=0.35,
            keywords=[],
            payload=payload,
        )
    )
    session.commit()


class TestPending:
    def test_returns_ungraded_news_rows(self, db_session):
        for i in range(3):
            _news_row(db_session, i)

        assert len(grade_run.pending(db_session, limit=10)) == 3

    def test_skips_rows_already_graded_by_the_model(self, db_session):
        """This is what makes a killed run resumable — graded rows are not redone."""
        _news_row(db_session, 0, method=news.METHOD)
        _news_row(db_session, 1)

        pending = grade_run.pending(db_session, limit=10)

        assert len(pending) == 1
        assert pending[0].payload["title"] == "headline 1"

    def test_a_re_run_after_a_partial_grade_covers_only_the_remainder(self, db_session):
        """Simulate an interrupted batch: some rows carry the LLM method, some do not."""
        for i in range(5):
            _news_row(db_session, i, method=news.METHOD if i < 2 else None)

        remaining = grade_run.pending(db_session, limit=10)

        assert {r.payload["title"] for r in remaining} == {
            "headline 2",
            "headline 3",
            "headline 4",
        }


class TestPendingCount:
    def test_counts_every_ungraded_row_not_just_a_page(self, db_session):
        """The batch is bounded by `limit`; the count must describe the table.

        The final log line is what a human reads to answer "did it finish?" —
        it has to speak about the table, not the page that was fetched (#644).
        """
        for i in range(7):
            _news_row(db_session, i)

        assert grade_run.pending_count(db_session) == 7
        assert len(grade_run.pending(db_session, limit=3)) == 3

    def test_ignores_rows_already_graded(self, db_session):
        _news_row(db_session, 0, method=news.METHOD)
        _news_row(db_session, 1)

        assert grade_run.pending_count(db_session) == 1


def _always_grades(row, *, model):
    """Stand-in for the model: every row gets a verdict, no Ollama involved."""
    return 0.6, {
        "severity_band": "grave",
        "severity_rationale": "test",
        "severity_method": news.METHOD,
    }


def _always_rejects(row, *, model):
    """Every row fails a guard — the case that must not spin forever."""
    return None


class TestRun:
    def test_one_pass_stops_at_the_limit(self, db_session):
        for i in range(5):
            _news_row(db_session, i)

        graded, skipped = grade_run.run(
            db_session, limit=2, model="m", apply=True, until_empty=False, grade=_always_grades
        )

        assert (graded, skipped) == (2, 0)
        assert grade_run.pending_count(db_session) == 3

    def test_until_empty_drains_the_table_across_passes(self, db_session):
        """The #644 defect: ingest outpaces one snapshot, so a run that
        grades a single batch always exits with a backlog behind it."""
        for i in range(5):
            _news_row(db_session, i)

        graded, skipped = grade_run.run(
            db_session, limit=2, model="m", apply=True, until_empty=True, grade=_always_grades
        )

        assert (graded, skipped) == (5, 0)
        assert grade_run.pending_count(db_session) == 0

    def test_until_empty_stops_when_a_pass_makes_no_progress(self, db_session):
        """A permanently-rejected row keeps appearing in `pending` forever —
        without a progress check, --until-empty would spin on it."""
        for i in range(3):
            _news_row(db_session, i)

        graded, skipped = grade_run.run(
            db_session, limit=2, model="m", apply=True, until_empty=True, grade=_always_rejects
        )

        assert graded == 0
        assert skipped == 2
        assert grade_run.pending_count(db_session) == 3

    def test_dry_run_writes_nothing(self, db_session):
        _news_row(db_session, 0)

        grade_run.run(
            db_session, limit=5, model="m", apply=False, until_empty=False, grade=_always_grades
        )

        assert grade_run.pending_count(db_session) == 1
