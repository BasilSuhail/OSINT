from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.brain import gate
from app.db_models import Base, JobRunRow


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_heavy_job_active_ignores_brain_enrich_row():
    session = _session()
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    session.add(JobRunRow(job="brain-enrich", status="running", heartbeat_at=now))
    session.commit()
    assert gate.heavy_job_active(session, now=now) is False


def test_heavy_job_active_ignores_brain_narrate_row():
    session = _session()
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    session.add(JobRunRow(job="brain-narrate", status="running", heartbeat_at=now))
    session.commit()
    assert gate.heavy_job_active(session, now=now) is False


def test_heavy_job_active_still_detects_real_job():
    session = _session()
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    session.add(JobRunRow(job="cluster_stories", status="running", heartbeat_at=now))
    session.commit()
    assert gate.heavy_job_active(session, now=now) is True


def test_prefix_constants_exist():
    assert gate.BRAIN_JOB_PREFIX == "brain-"
    assert gate.BRAIN_ENRICH_JOB_NAME == "brain-enrich"
    assert gate.BRAIN_JOB_NAME.startswith(gate.BRAIN_JOB_PREFIX)
