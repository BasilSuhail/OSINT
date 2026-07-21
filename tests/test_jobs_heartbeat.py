"""Tests for `app.jobs.heartbeat` and the /jobs/recent endpoint (#341)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import app, get_session
from app.db_models import Base, JobRunRow
from app.jobs.heartbeat import job_run


@pytest.fixture
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    engine.dispose()


def _rows(factory: sessionmaker[Session]) -> list[JobRunRow]:
    with factory() as session:
        return list(session.execute(select(JobRunRow)).scalars())


class TestJobRun:
    def test_success_records_done_with_progress(self, factory) -> None:
        with job_run("labels", session_factory=factory) as progress:
            progress("loading xlsx")
            progress("9171 labels upserted")
        (row,) = _rows(factory)
        assert row.job == "labels"
        assert row.status == "done"
        assert row.progress == "9171 labels upserted"
        assert row.finished_at is not None
        assert row.detail is None

    def test_exception_records_failed_and_reraises(self, factory) -> None:
        with (
            pytest.raises(RuntimeError, match="boom"),
            job_run("backfill-signals", session_factory=factory),
        ):
            raise RuntimeError("boom")
        (row,) = _rows(factory)
        assert row.status == "failed"
        assert row.detail == "boom"
        assert row.finished_at is not None

    def test_progress_visible_mid_run(self, factory) -> None:
        with job_run("panel", session_factory=factory) as progress:
            progress("assembling")
            (row,) = _rows(factory)  # read while still running
            assert row.status == "running"
            assert row.progress == "assembling"

    def test_old_finished_runs_pruned_on_start(self, factory) -> None:
        ancient = datetime.now(UTC) - timedelta(days=30)
        with factory() as session:
            session.add(
                JobRunRow(
                    job="old",
                    status="done",
                    started_at=ancient,
                    heartbeat_at=ancient,
                    finished_at=ancient,
                )
            )
            session.commit()
        with job_run("labels", session_factory=factory):
            pass
        assert {row.job for row in _rows(factory)} == {"labels"}


class TestJobsRecentEndpoint:
    def test_serves_runs_newest_first(self, factory) -> None:
        with job_run("labels", session_factory=factory):
            pass
        with pytest.raises(RuntimeError), job_run("panel", session_factory=factory):
            raise RuntimeError("exploded")

        session = factory()
        app.dependency_overrides[get_session] = lambda: session
        try:
            body = TestClient(app).get("/jobs/recent?hours=48").json()
        finally:
            app.dependency_overrides.clear()
            session.close()

        assert [run["job"] for run in body] == ["panel", "labels"]
        assert body[0]["status"] == "failed"
        assert body[0]["detail"] == "exploded"
        assert body[1]["status"] == "done"
        assert body[1]["finished_at"] is not None


class TestAbandonedRunReaping:
    """A job killed without unwinding leaves its row `running` forever (#564).

    SIGTERM — which is what `scripts/dev-down.sh` sends — does not raise in
    Python, so `except BaseException` never runs and the row is never closed.
    The next run of the same job reconciles it.
    """

    def _abandoned(self, factory, *, job: str, minutes_stale: int) -> int:
        stale = datetime.now(UTC) - timedelta(minutes=minutes_stale)
        with factory() as session:
            row = JobRunRow(job=job, status="running", started_at=stale, heartbeat_at=stale)
            session.add(row)
            session.commit()
            return row.id

    def test_a_stale_running_row_is_marked_failed_on_the_next_run(self, factory) -> None:
        abandoned = self._abandoned(factory, job="validator", minutes_stale=90)
        with job_run("validator", session_factory=factory):
            pass
        with factory() as session:
            row = session.get(JobRunRow, abandoned)
        assert row.status == "failed"
        assert row.finished_at is not None

    def test_the_reaped_row_says_why_rather_than_staying_silent(self, factory) -> None:
        # The whole complaint: it died and recorded nothing. A reader must be
        # able to tell "killed" from "still working".
        abandoned = self._abandoned(factory, job="validator", minutes_stale=90)
        with job_run("validator", session_factory=factory):
            pass
        with factory() as session:
            row = session.get(JobRunRow, abandoned)
        assert row.detail and "abandoned" in row.detail.lower()

    def test_a_fresh_running_row_is_left_alone(self, factory) -> None:
        # Two workers can legitimately run the same job concurrently; a live
        # one must not be declared dead by the other starting.
        live = self._abandoned(factory, job="validator", minutes_stale=0)
        with job_run("validator", session_factory=factory):
            pass
        with factory() as session:
            assert session.get(JobRunRow, live).status == "running"

    def test_another_job_s_abandoned_row_is_not_touched(self, factory) -> None:
        other = self._abandoned(factory, job="journal", minutes_stale=90)
        with job_run("validator", session_factory=factory):
            pass
        with factory() as session:
            assert session.get(JobRunRow, other).status == "running"

    def test_a_finished_row_is_never_rewritten(self, factory) -> None:
        old = datetime.now(UTC) - timedelta(minutes=90)
        with factory() as session:
            row = JobRunRow(
                job="validator",
                status="done",
                started_at=old,
                heartbeat_at=old,
                finished_at=old,
            )
            session.add(row)
            session.commit()
            done_id = row.id
        with job_run("validator", session_factory=factory):
            pass
        with factory() as session:
            assert session.get(JobRunRow, done_id).status == "done"


class TestAutomaticHeartbeat:
    """A live job must prove it is alive without the call site remembering.

    Fourteen of fifteen call sites never called `progress()`, so their
    heartbeat was frozen at `started_at` and the API's "stale means dead" rule
    reported every long job as a corpse (#564).
    """

    def test_the_heartbeat_advances_without_any_progress_call(self, factory) -> None:
        from app.jobs import heartbeat as hb

        with job_run("validator", session_factory=factory, heartbeat_interval_s=0.05):
            _wait_for_heartbeat_bump(factory)
        (row,) = _rows(factory)
        assert row.heartbeat_at > row.started_at, "a live job never proved it was alive"
        assert hb  # module import kept explicit for the reader

    def test_progress_still_publishes_a_human_readable_line(self, factory) -> None:
        with job_run("labels", session_factory=factory, heartbeat_interval_s=0.05) as progress:
            progress("still working")
        (row,) = _rows(factory)
        assert row.progress == "still working"

    def test_the_bumper_stops_when_the_job_ends(self, factory) -> None:
        with job_run("validator", session_factory=factory, heartbeat_interval_s=0.05):
            _wait_for_heartbeat_bump(factory)
        (row,) = _rows(factory)
        settled = row.heartbeat_at
        time.sleep(0.2)
        (row,) = _rows(factory)
        assert row.heartbeat_at == settled, "the bumper outlived the job"

    def test_a_failing_job_still_records_the_failure(self, factory) -> None:
        with pytest.raises(RuntimeError), job_run("validator", session_factory=factory):
            raise RuntimeError("ollama down")
        (row,) = _rows(factory)
        assert row.status == "failed"
        assert "ollama down" in row.detail


def _wait_for_heartbeat_bump(factory, timeout_s: float = 3.0) -> None:
    """Block until the background bumper has advanced the heartbeat once."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with factory() as session:
            row = session.execute(select(JobRunRow)).scalars().first()
            if row is not None and row.heartbeat_at > row.started_at:
                return
        time.sleep(0.02)
    raise AssertionError("heartbeat never advanced")
