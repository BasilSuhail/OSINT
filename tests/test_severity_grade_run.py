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
