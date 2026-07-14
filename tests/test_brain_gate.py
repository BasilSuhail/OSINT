from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.brain import gate
from app.db_models import Base, JobRunRow

MEMINFO = """MemTotal:        8000000 kB
MemFree:          500000 kB
MemAvailable:    2048000 kB
Buffers:          100000 kB
"""

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                          65536.
Pages inactive:                      65536.
Pages active:                       100000.
"""


def test_parse_meminfo_returns_available_mb():
    assert gate._parse_meminfo(MEMINFO) == 2000  # 2048000 kB / 1024


def test_parse_vm_stat_returns_free_plus_inactive_mb():
    # (65536 + 65536) pages * 16384 bytes = 2 GiB = 2048 MB
    assert gate._parse_vm_stat(VM_STAT) == 2048


def _memory_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_heavy_job_active_true_for_fresh_running_row():
    session = _memory_session()
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    session.add(JobRunRow(job="cluster", status="running", heartbeat_at=now))
    session.commit()
    assert gate.heavy_job_active(session, now=now) is True


def test_heavy_job_active_false_for_stale_heartbeat():
    session = _memory_session()
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    session.add(JobRunRow(job="cluster", status="running", heartbeat_at=now - timedelta(minutes=5)))
    session.commit()
    assert gate.heavy_job_active(session, now=now) is False


def test_heavy_job_active_false_for_done_row():
    session = _memory_session()
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    session.add(JobRunRow(job="cluster", status="done", heartbeat_at=now))
    session.commit()
    assert gate.heavy_job_active(session, now=now) is False


def test_should_run_blocks_when_ram_low(monkeypatch):
    session = _memory_session()
    monkeypatch.setattr(gate, "ram_free_mb", lambda: 500)
    monkeypatch.setattr(gate.settings, "brain_min_free_mb", 1200)
    allowed, reason = gate.should_run(session)
    assert allowed is False
    assert "ram" in reason.lower()


def test_should_run_allows_when_idle_and_ram_ok(monkeypatch):
    session = _memory_session()
    monkeypatch.setattr(gate, "ram_free_mb", lambda: 4000)
    monkeypatch.setattr(gate.runtime_load, "busy_reason", lambda now=None: None)
    allowed, _reason = gate.should_run(session)
    assert allowed is True


def test_should_run_blocks_when_runtime_busy(monkeypatch):
    session = _memory_session()
    monkeypatch.setattr(gate, "ram_free_mb", lambda: 4000)
    monkeypatch.setattr(gate.runtime_load, "busy_reason", lambda now=None: "eval active")

    allowed, reason = gate.should_run(session)

    assert allowed is False
    assert reason == "eval active"


def test_heavy_job_active_false_for_own_fresh_brain_row():
    """#409: the brain's own job_run row must never count as heavy work it
    has to back off from — only other jobs do."""
    session = _memory_session()
    now = datetime.now(UTC)
    session.add(JobRunRow(job=gate.BRAIN_JOB_NAME, status="running", heartbeat_at=now))
    session.commit()
    assert gate.heavy_job_active(session, now=now) is False


def test_heavy_job_active_true_for_other_job_same_freshness():
    session = _memory_session()
    now = datetime.now(UTC)
    session.add(JobRunRow(job="cluster", status="running", heartbeat_at=now))
    session.commit()
    assert gate.heavy_job_active(session, now=now) is True
