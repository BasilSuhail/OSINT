"""The scheduled severity pass (#631).

The point of the beat is that nobody has to remember it, so the tests are about
the properties that make it safe to leave running: it grades only what is
ungraded, a rejected verdict never overwrites a stored grade, and one bad batch
does not cost the rows around it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db_models import EventRow
from app.severity import grade_run, news, task


def _news_row(session, i, *, method=None, severity=0.35, title=None):
    payload = {"title": title if title is not None else f"headline {i}"}
    if method:
        payload["severity_method"] = method
    session.add(
        EventRow(
            source="rss-test",
            source_event_id=f"n{i}",
            occurred_at=datetime(2026, 7, 1, tzinfo=UTC) - timedelta(minutes=i),
            fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
            category="news",
            severity=severity,
            keywords=[],
            payload=payload,
        )
    )
    session.commit()


class TestPendingBoundsTheQuery:
    """The overfetch that made a whole-table regrade hold 3.4 GB of ORM rows."""

    def test_returns_no_more_than_the_limit(self, db_session):
        for i in range(10):
            _news_row(db_session, i)

        assert len(grade_run.pending(db_session, limit=3)) == 3

    def test_the_limit_applies_after_graded_rows_are_excluded(self, db_session):
        """Graded rows must not consume the budget: filtering happens in SQL, so
        a limit of 3 returns 3 ungraded rows even when graded rows sort first."""
        for i in range(4):
            _news_row(db_session, i, method=news.METHOD)
        for i in range(4, 10):
            _news_row(db_session, i)

        rows = grade_run.pending(db_session, limit=3)

        assert len(rows) == 3
        assert all(r.payload.get("severity_method") != news.METHOD for r in rows)

    def test_rows_missing_the_key_entirely_are_still_pending(self, db_session):
        """`payload` has no `severity_method` at all before the model runs, and
        SQL NULL never satisfies `!=`, so the null case must be explicit."""
        _news_row(db_session, 0)

        assert len(grade_run.pending(db_session, limit=10)) == 1


class TestGradeBody:
    @pytest.fixture(autouse=True)
    def _scope(self, db_session, monkeypatch):
        """Point the body at the test session and neutralise the heartbeat."""
        import contextlib

        monkeypatch.setattr(task, "session_scope", lambda: contextlib.nullcontext(db_session))
        monkeypatch.setattr(
            task, "job_run", lambda *a, **k: contextlib.nullcontext(lambda _t: None)
        )

    def test_grades_ungraded_rows_and_stamps_the_method(self, db_session, monkeypatch):
        _news_row(db_session, 0)
        monkeypatch.setattr(
            task.grade_run,
            "grade_row",
            lambda row, *, model: (
                0.8,
                {
                    "severity_method": news.METHOD,
                    "severity_band": "grave",
                    "severity_rationale": "eight killed in a bombing",
                },
            ),
        )

        result = task._grade_body(batch_limit=10)

        assert result == {"considered": 1, "graded": 1, "rejected": 0}
        row = db_session.query(EventRow).one()
        assert row.severity == 0.8
        assert row.payload["severity_method"] == news.METHOD
        assert row.payload["title"] == "headline 0"  # existing payload survives

    def test_a_rejected_verdict_leaves_the_stored_grade_alone(self, db_session, monkeypatch):
        """A guard rejection must never downgrade a row to nothing — the point
        of returning None is that the old value is better than a suspect one."""
        _news_row(db_session, 0, severity=0.65)
        monkeypatch.setattr(task.grade_run, "grade_row", lambda row, *, model: None)

        result = task._grade_body(batch_limit=10)

        assert result == {"considered": 1, "graded": 0, "rejected": 1}
        row = db_session.query(EventRow).one()
        assert row.severity == 0.65
        assert "severity_method" not in row.payload

    def test_one_rejection_does_not_stop_the_batch(self, db_session, monkeypatch):
        for i in range(3):
            _news_row(db_session, i)
        calls = {"n": 0}

        def _grade(row, *, model):
            calls["n"] += 1
            if calls["n"] == 2:
                return None
            return (0.2, {"severity_method": news.METHOD})

        monkeypatch.setattr(task.grade_run, "grade_row", _grade)

        assert task._grade_body(batch_limit=10) == {
            "considered": 3,
            "graded": 2,
            "rejected": 1,
        }

    def test_already_graded_rows_are_not_regraded(self, db_session, monkeypatch):
        """What makes the beat cheap to run twice hourly: it idles once caught up."""
        _news_row(db_session, 0, method=news.METHOD)
        monkeypatch.setattr(
            task.grade_run,
            "grade_row",
            lambda row, *, model: pytest.fail("graded row was regraded"),
        )

        assert task._grade_body(batch_limit=10) == {
            "considered": 0,
            "graded": 0,
            "rejected": 0,
        }


class TestScheduled:
    def test_the_beat_entry_exists_and_points_at_the_task(self):
        """The whole issue is that this was never scheduled."""
        from app.tasks import app

        entry = app.conf.beat_schedule["severity-grade-30min"]

        assert entry["task"] == "app.tasks.grade_news_severity"

    def test_a_busy_box_skips_instead_of_grading(self, monkeypatch):
        import app.tasks as tasks

        monkeypatch.setattr(
            tasks, "_skip_optional_heavy", lambda: {"skipped": True, "reason": "busy"}
        )
        monkeypatch.setattr(task, "_grade_body", lambda **k: pytest.fail("ran while busy"))

        assert tasks.grade_news_severity() == {"skipped": True, "reason": "busy"}
