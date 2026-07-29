"""The job-failure watchdog (#657).

`sensor-checks` failed 717 times in 24 hours and nothing told anyone. The
reaper from #564 recorded every failure faithfully; nobody reads `job_runs`
unprompted. These tests pin the two shapes a broken job takes — going quiet,
and failing every time while staying fresh — and, just as importantly, the
cases that must stay silent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import tasks
from app.db_models import JobRunRow, NotificationRow
from app.watchdog import (
    JOB_CADENCE_MIN,
    JOB_MAX_FAILURE_RATE,
    JOB_RECENT_RUNS,
    check_jobs,
    job_stale_after,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _run(
    session: Session,
    job: str,
    *,
    status: str,
    minutes_ago: int,
    detail: str | None = None,
) -> None:
    started = NOW - timedelta(minutes=minutes_ago)
    session.add(
        JobRunRow(
            job=job,
            status=status,
            started_at=started,
            heartbeat_at=started,
            finished_at=None if status == "running" else started,
            detail=detail,
        )
    )


def _check(session: Session) -> dict:
    with patch("app.watchdog._pushover_send"):
        report = check_jobs(session, now=NOW)
    session.commit()
    return report


class TestGoingQuiet:
    def test_the_656_outage_would_have_paged(self, db_session: Session) -> None:
        # sensor-checks last succeeded 2026-07-25 21:48 and then failed every
        # 30 minutes for two days. Its cadence is 30 min, so it is stale after
        # 90 — this should have fired on day one, not been found by an audit.
        _run(db_session, "sensor-checks", status="done", minutes_ago=2_800)
        for offset in range(0, 300, 30):
            _run(
                db_session,
                "sensor-checks",
                status="failed",
                minutes_ago=offset,
                detail="abandoned: no heartbeat for over 30 minutes and a later run started.",
            )
        db_session.commit()

        report = _check(db_session)

        assert report["sensor-checks"]["is_stale"] is True
        assert report["sensor-checks"]["alerted"] is True

    def test_the_page_quotes_what_the_job_last_recorded(self, db_session: Session) -> None:
        # The reaper's detail already explains the cause. A page that repeats
        # it is actionable; one that just says "stale" sends you to psql.
        _run(db_session, "sensor-checks", status="done", minutes_ago=2_800)
        _run(
            db_session,
            "sensor-checks",
            status="failed",
            minutes_ago=5,
            detail="abandoned: killed without unwinding (OOM kill)",
        )
        db_session.commit()

        _check(db_session)

        (row,) = db_session.execute(select(NotificationRow)).scalars().all()
        assert "sensor-checks" in row.message
        assert "OOM kill" in row.message

    def test_a_job_succeeding_on_cadence_stays_silent(self, db_session: Session) -> None:
        _run(db_session, "sensor-checks", status="done", minutes_ago=20)
        db_session.commit()

        report = _check(db_session)

        assert report["sensor-checks"]["is_stale"] is False
        assert report["sensor-checks"]["alerted"] is False
        assert db_session.execute(select(NotificationRow)).scalars().all() == []


class TestFailingWhileFresh:
    def test_a_job_that_mostly_fails_is_flagged_even_when_fresh(self, db_session: Session) -> None:
        # The second shape: it keeps succeeding just often enough never to look
        # stale, and fails the rest of the time. Nothing downstream can trust it.
        _run(db_session, "disagreement", status="done", minutes_ago=10)
        for offset in range(20, 200, 20):
            _run(db_session, "disagreement", status="failed", minutes_ago=offset)
        db_session.commit()

        report = _check(db_session)

        assert report["disagreement"]["is_stale"] is False
        assert report["disagreement"]["is_failing"] is True
        assert report["disagreement"]["alerted"] is True

    def test_one_bad_run_among_many_good_ones_is_not_an_alarm(self, db_session: Session) -> None:
        _run(db_session, "disagreement", status="failed", minutes_ago=100)
        for offset in range(0, 90, 10):
            _run(db_session, "disagreement", status="done", minutes_ago=offset)
        db_session.commit()

        report = _check(db_session)

        assert report["disagreement"]["is_failing"] is False
        assert report["disagreement"]["alerted"] is False


class TestStayingQuiet:
    def test_a_job_that_has_never_run_does_not_page(self, db_session: Session) -> None:
        # On a fresh database that is every job at once, which is noise.
        report = _check(db_session)

        assert all(state["alerted"] is False for state in report.values())
        assert db_session.execute(select(NotificationRow)).scalars().all() == []

    def test_one_shot_jobs_are_not_watched(self) -> None:
        # These legitimately go months between runs. Paging on them would train
        # everyone to ignore the channel.
        for job in ("backfill-signals", "panel", "baselines", "labels", "onset-eval"):
            assert job not in JOB_CADENCE_MIN

    def test_a_run_still_in_flight_counts_neither_way(self, db_session: Session) -> None:
        _run(db_session, "sensor-checks", status="done", minutes_ago=20)
        _run(db_session, "sensor-checks", status="running", minutes_ago=1)
        db_session.commit()

        report = _check(db_session)

        assert report["sensor-checks"]["considered_recent"] == 1
        assert report["sensor-checks"]["alerted"] is False

    def test_one_page_per_job_per_day(self, db_session: Session) -> None:
        # 717 failures must produce one notification, not 717.
        _run(db_session, "sensor-checks", status="done", minutes_ago=2_800)
        _run(db_session, "sensor-checks", status="failed", minutes_ago=5)
        db_session.commit()

        first = _check(db_session)
        second = _check(db_session)

        assert first["sensor-checks"]["alerted"] is True
        assert second["sensor-checks"]["alerted"] is False
        assert len(db_session.execute(select(NotificationRow)).scalars().all()) == 1


class TestThresholds:
    def test_a_frequent_job_is_judged_on_its_own_cadence(self) -> None:
        assert job_stale_after(15) == timedelta(minutes=45)
        assert job_stale_after(30) == timedelta(minutes=90)

    def test_a_long_cadence_job_gets_a_day_of_grace_not_triple_its_cadence(self) -> None:
        # Tripling a weekly cadence means silence for three weeks. Capping the
        # extra grace at a day means a missed weekly briefing is heard about
        # while it still matters.
        assert job_stale_after(1440) == timedelta(minutes=2880)
        assert job_stale_after(10080) == timedelta(minutes=11520)

    def test_every_watched_job_is_one_the_beat_actually_schedules(self) -> None:
        # The cadences mirror `beat_schedule` by hand, so this is the test that
        # catches the two drifting apart.
        scheduled = {
            entry["task"].removeprefix("app.tasks.")
            for entry in tasks.app.conf.beat_schedule.values()
        }
        job_to_task = {
            "brain-narrate": "brain_narrate",
            "brain-enrich": "brain_enrich",
            "stories-cluster": "cluster_stories",
            "sensor-checks": "sensor_check_stories",
            "disagreement": "score_disagreement",
            "severity-grade": "grade_news_severity",
            "journal": "journal_daily",
            "validator": "extract_claims",
            "data-audit": "data_audit",
            "briefing": "weekly_briefing",
        }
        assert set(job_to_task) == set(JOB_CADENCE_MIN)
        for job, task_name in job_to_task.items():
            assert task_name in scheduled, f"{job} is watched but no longer scheduled"

    def test_failure_rate_threshold_is_a_majority(self) -> None:
        assert 0 < JOB_MAX_FAILURE_RATE < 1
        assert JOB_RECENT_RUNS >= 5
