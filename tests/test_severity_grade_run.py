"""The regrade batch runner — resumable, incremental (#596).

A full news regrade is ~13h of model calls. It must never be one transaction
that saves nothing when interrupted, and a re-run must pick up where a killed
one stopped rather than starting over.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.db_models import EventRow
from app.severity import grade_run, news


def _news_row(session, i, *, method=None, source="rss-test"):
    payload = {"title": f"headline {i}"}
    if method:
        payload["severity_method"] = method
    session.add(
        EventRow(
            source=source,
            source_event_id=f"{source}-n{i}",
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
    def test_rejects_a_non_positive_limit(self, db_session):
        import pytest

        with pytest.raises(ValueError, match="limit must be positive"):
            grade_run.pending(db_session, limit=0)

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

    def test_one_source_cannot_consume_a_batch_while_another_is_pending(self, db_session):
        for i in range(5):
            _news_row(db_session, i, source="rss-firehose")
        _news_row(db_session, 99, source="rss-quiet")

        rows = grade_run.pending(db_session, limit=2)

        assert {row.source for row in rows} == {"rss-firehose", "rss-quiet"}

    def test_sources_omitted_by_a_small_batch_are_prioritised_next(self, db_session):
        for source in ("rss-a", "rss-b", "rss-c"):
            _news_row(db_session, 0, source=source)

        first = grade_run.pending(db_session, limit=2)
        for row in first:
            grade_run.apply_grade(
                db_session, row, value=0.6, payload=_always_grades(row, model="m")[1]
            )
        db_session.commit()

        second = grade_run.pending(db_session, limit=1)

        assert second[0].source == ({"rss-a", "rss-b", "rss-c"} - {r.source for r in first}).pop()

    def test_low_progress_firehose_cannot_monopolise_a_batch(self, db_session):
        for i in range(100):
            _news_row(db_session, i, source="rss-new-firehose")
        for i in range(101):
            _news_row(
                db_session,
                i,
                source="rss-mature",
                method=news.METHOD if i < 100 else None,
            )

        rows = grade_run.pending(db_session, limit=50)

        assert [row.source for row in rows].count("rss-new-firehose") == 49
        assert [row.source for row in rows].count("rss-mature") == 1

    def test_oldest_pending_row_in_each_source_is_protected_first(self, db_session):
        for i in range(4):
            _news_row(db_session, i)

        rows = grade_run.pending(db_session, limit=1)

        assert rows[0].payload["title"] == "headline 3"

    def test_non_rss_news_rows_are_outside_the_grading_protocol(self, db_session):
        _news_row(db_session, 0, source="uk-police")

        assert grade_run.pending(db_session, limit=10) == []
        assert grade_run.pending_count(db_session) == 0

    def test_a_rejected_head_does_not_block_later_rows_from_its_source(self, db_session):
        _news_row(db_session, 0)
        _news_row(db_session, 1)
        calls = {"n": 0}

        def _reject_then_grade(row, *, model):
            calls["n"] += 1
            return None if calls["n"] == 1 else _always_grades(row, model=model)

        graded, skipped = grade_run.run(
            db_session,
            limit=1,
            model="m",
            apply=True,
            until_empty=True,
            grade=_reject_then_grade,
        )

        assert (graded, skipped) == (1, 1)
        assert grade_run.pending_count(db_session) == 0

    def test_changed_headline_retries_a_rejected_row(self, db_session):
        _news_row(db_session, 0)
        row = db_session.query(EventRow).one()
        grade_run.mark_rejected(db_session, row)
        db_session.commit()
        assert grade_run.pending(db_session, limit=1) == []

        row.payload = {**row.payload, "title": "corrected headline"}
        db_session.commit()

        assert grade_run.pending(db_session, limit=1) == [row]

    def test_rejection_cannot_overwrite_a_concurrent_headline_refresh(self, db_session):
        _news_row(db_session, 0)
        row = db_session.query(EventRow).one()
        old_title = row.payload["title"]
        db_session.execute(
            update(EventRow)
            .where(EventRow.id == row.id)
            .values(payload={**row.payload, "title": "new headline", "summary": "new metadata"})
        )

        assert not grade_run.mark_rejected(db_session, row, expected_title=old_title)
        db_session.expire(row)
        assert row.payload["title"] == "new headline"
        assert row.payload["summary"] == "new metadata"
        assert grade_run.ATTEMPTED_METHOD_KEY not in row.payload


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


def test_successful_retry_clears_an_older_rejection_stamp(db_session):
    _news_row(db_session, 0)
    row = db_session.query(EventRow).one()
    row.payload = {
        **row.payload,
        grade_run.ATTEMPTED_METHOD_KEY: "news-llm-v0",
        grade_run.ATTEMPTED_INPUT_KEY: "headline 0",
        "severity_grade_attempted_at": "2026-01-01T00:00:00+00:00",
        "severity_grade_status": "rejected",
    }
    db_session.commit()

    grade_run.run(
        db_session, limit=1, model="m", apply=True, until_empty=False, grade=_always_grades
    )

    assert row.payload["severity_method"] == news.METHOD
    assert row.payload[grade_run.COMPLETED_AT_KEY]
    assert grade_run.ATTEMPTED_METHOD_KEY not in row.payload
    assert grade_run.ATTEMPTED_INPUT_KEY not in row.payload
    assert "severity_grade_attempted_at" not in row.payload
    assert "severity_grade_status" not in row.payload


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

    def test_until_empty_stamps_rejections_and_drains_them(self, db_session):
        """A permanent rejection is terminal for this method, not a loop."""
        for i in range(3):
            _news_row(db_session, i)

        graded, skipped = grade_run.run(
            db_session, limit=2, model="m", apply=True, until_empty=True, grade=_always_rejects
        )

        assert graded == 0
        assert skipped == 3
        assert grade_run.pending_count(db_session) == 0

    def test_dry_run_until_empty_stops_after_one_snapshot(self, db_session):
        for i in range(3):
            _news_row(db_session, i)

        graded, skipped = grade_run.run(
            db_session, limit=2, model="m", apply=False, until_empty=True, grade=_always_grades
        )

        assert (graded, skipped) == (2, 0)
        assert grade_run.pending_count(db_session) == 3

    def test_dry_run_writes_nothing(self, db_session):
        _news_row(db_session, 0)

        grade_run.run(
            db_session, limit=5, model="m", apply=False, until_empty=False, grade=_always_grades
        )

        assert grade_run.pending_count(db_session) == 1
