"""Tests for `app.jobs.heartbeat` and the /jobs/recent endpoint (#341)."""

from __future__ import annotations

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
