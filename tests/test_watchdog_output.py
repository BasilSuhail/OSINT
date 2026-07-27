"""The output watchdog (#663).

#659 asks whether a job ran. This asks whether it did anything. The brain
returned `done` 63 times in a day while producing no narrative, and every check
in the system correctly saw nothing wrong, because backing off is a success.

The risk here is the opposite of #659's: a check that pages on a job doing
nothing *because there was nothing to do* trains everyone to ignore the
channel. So the silent cases are tested as hard as the loud one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import BrainNarrativeRow, JobRunRow, NotificationRow
from app.watchdog import (
    JOB_CADENCE_MIN,
    JOB_OUTPUT,
    check_output,
    output_stale_after,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _narrative(session: Session, *, minutes_ago: int) -> None:
    session.add(
        BrainNarrativeRow(
            model="test-model",
            payload={"text": "a narrative"},
            input_digest=f"digest-{minutes_ago}",
            created_at=NOW - timedelta(minutes=minutes_ago),
        )
    )


def _run(session: Session, job: str, *, minutes_ago: int, detail: str | None = None) -> None:
    started = NOW - timedelta(minutes=minutes_ago)
    session.add(
        JobRunRow(
            job=job,
            status="done",
            started_at=started,
            heartbeat_at=started,
            finished_at=started,
            detail=detail,
        )
    )


def _check(session: Session) -> dict:
    with patch("app.watchdog._pushover_send"):
        report = check_output(session, now=NOW)
    session.commit()
    return report


class TestTheBrainCase:
    def test_a_job_that_runs_but_produces_nothing_is_flagged(self, db_session: Session) -> None:
        # #413 exactly: healthy runs every 15 min, no narrative for six hours.
        _narrative(db_session, minutes_ago=360)
        for offset in range(0, 300, 15):
            _run(db_session, "brain-narrate", minutes_ago=offset)
        db_session.commit()

        report = _check(db_session)

        assert report["brain-narrate"]["is_stale"] is True
        assert report["brain-narrate"]["alerted"] is True

    def test_the_page_carries_the_diagnosis_not_just_the_alarm(self, db_session: Session) -> None:
        # "produced nothing for 6h" sends you to psql. The reason the job itself
        # recorded is what makes it actionable.
        _narrative(db_session, minutes_ago=360)
        _run(
            db_session,
            "brain-narrate",
            minutes_ago=5,
            detail="low RAM: 1072MB free < 1200MB floor",
        )
        db_session.commit()

        _check(db_session)

        (row,) = db_session.execute(select(NotificationRow)).scalars().all()
        assert "brain-narrate" in row.message
        assert "produced nothing" in row.message
        assert "1072MB free" in row.message


class TestStayingQuiet:
    def test_downtime_does_not_page_on_restart(self, db_session: Session) -> None:
        # The stack was off 01:15-10:32 on 2026-07-27. The first sweep after
        # restart sees a 556-minute gap in every output table. That is "was not
        # running", which is #657's question — not this one. No run in the
        # window, so nothing to say.
        _narrative(db_session, minutes_ago=556)
        db_session.commit()

        report = _check(db_session)

        assert report["brain-narrate"]["ran_in_window"] is False
        assert report["brain-narrate"]["is_stale"] is False
        assert db_session.execute(select(NotificationRow)).scalars().all() == []

    def test_a_producing_job_says_nothing(self, db_session: Session) -> None:
        _narrative(db_session, minutes_ago=5)
        db_session.commit()

        report = _check(db_session)

        assert report["brain-narrate"]["is_stale"] is False
        assert db_session.execute(select(NotificationRow)).scalars().all() == []

    def test_a_job_that_has_never_produced_anything_does_not_page(
        self, db_session: Session
    ) -> None:
        # A fresh database is every job at once. Paging on first boot is how a
        # channel gets ignored.
        report = _check(db_session)

        assert all(state["alerted"] is False for state in report.values())
        assert db_session.execute(select(NotificationRow)).scalars().all() == []

    def test_severity_grade_is_not_watched(self) -> None:
        # The design decision of the whole check. Its backlog legitimately
        # empties — `{"considered": 0}` with nothing pending is correct and is
        # the normal steady state since #631. Watching it would page on success.
        assert "severity-grade" not in JOB_OUTPUT
        assert "severity-grade" in JOB_CADENCE_MIN

    def test_a_short_skip_while_the_box_is_busy_does_not_page(self, db_session: Session) -> None:
        # These jobs back off by design when Basil is working (#409). An hour of
        # that on a 15-minute job must stay silent.
        _narrative(db_session, minutes_ago=60)
        db_session.commit()

        report = _check(db_session)

        assert report["brain-narrate"]["is_stale"] is False

    def test_one_page_per_job_per_day(self, db_session: Session) -> None:
        _narrative(db_session, minutes_ago=360)
        _run(db_session, "brain-narrate", minutes_ago=5)
        db_session.commit()

        first = _check(db_session)
        second = _check(db_session)

        assert first["brain-narrate"]["alerted"] is True
        assert second["brain-narrate"]["alerted"] is False
        assert len(db_session.execute(select(NotificationRow)).scalars().all()) == 1


class TestThresholds:
    def test_the_window_is_looser_than_the_failure_check(self) -> None:
        # Deliberately: a failing job is broken now, a quiet one may just be
        # backing off. 15-minute narrator gets two hours before anyone hears.
        assert output_stale_after(15) == timedelta(minutes=120)
        assert output_stale_after(30) == timedelta(minutes=240)

    def test_a_long_cadence_job_gets_a_day_of_grace_not_eight_cadences(self) -> None:
        assert output_stale_after(1440) == timedelta(minutes=2880)

    def test_every_watched_job_has_a_cadence(self) -> None:
        # The two tables are maintained by hand; this is what catches drift.
        for job in JOB_OUTPUT:
            assert job in JOB_CADENCE_MIN, f"{job} has output watched but no cadence"
