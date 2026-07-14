"""The brain's resource gate (#409): may the model run right now?

Two cheap checks, no new dependency:
  1. RAM headroom — stdlib only (/proc/meminfo on Linux, vm_stat on macOS).
  2. No heavy job in flight — a job_runs row still `running` with a fresh
     heartbeat. That table already tracks every heavy analytical job; the
     I/O-bound fetchers deliberately don't use it, so it is a true
     "heavy work in progress" signal.
"""

from __future__ import annotations

import platform
import subprocess
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import JobRunRow
from app.runtime import load as runtime_load
from app.settings import settings

#: A job whose heartbeat is older than this is treated as dead, not busy.
_HEARTBEAT_FRESH_S: int = 90

#: The brain's own job names share this prefix; they are excluded from the
#: heavy-job check so a brain task never backs off from a job_run row it just
#: opened on itself (the Phase 1 self-block, #410 — now generalized to every
#: brain job so brain-enrich doesn't reintroduce it).
BRAIN_JOB_PREFIX = "brain-"
BRAIN_JOB_NAME = "brain-narrate"
BRAIN_ENRICH_JOB_NAME = "brain-enrich"


def _parse_meminfo(text: str) -> int:
    """MB available from /proc/meminfo (MemAvailable is in kB)."""
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    raise ValueError("MemAvailable not found in /proc/meminfo")


def _parse_vm_stat(text: str) -> int:
    """MB (free + inactive pages) from macOS `vm_stat` output."""
    page_size = 4096
    first = text.splitlines()[0]
    if "page size of" in first:
        page_size = int(first.split("page size of")[1].split("bytes")[0].strip())
    pages = {"free": 0, "inactive": 0}
    for line in text.splitlines():
        low = line.lower()
        for key in pages:
            if low.startswith(f"pages {key}:"):
                pages[key] = int(line.rsplit(":", 1)[1].strip().rstrip("."))
    return (pages["free"] + pages["inactive"]) * page_size // (1024 * 1024)


def ram_free_mb() -> int:
    """Best-effort free RAM in MB. On unknown platforms, return a large number
    so the gate never blocks purely on a RAM read we cannot perform."""
    system = platform.system()
    if system == "Linux":
        with open("/proc/meminfo", encoding="utf-8") as handle:
            return _parse_meminfo(handle.read())
    if system == "Darwin":
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, check=True)
        return _parse_vm_stat(out.stdout)
    return 1 << 20


def heavy_job_active(session: Session, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(seconds=_HEARTBEAT_FRESH_S)
    row = session.execute(
        select(JobRunRow.id)
        .where(
            JobRunRow.status == "running",
            JobRunRow.heartbeat_at >= cutoff,
            JobRunRow.job.not_like(f"{BRAIN_JOB_PREFIX}%"),
        )
        .limit(1)
    ).first()
    return row is not None


def should_run(session: Session, *, now: datetime | None = None) -> tuple[bool, str]:
    """(allowed, human reason). Reason powers the task log and the card's
    degraded state so backoff is visible, never a silent lie."""
    if not settings.brain_enabled:
        return False, "brain disabled (brain_enabled=false)"
    free = ram_free_mb()
    if free < settings.brain_min_free_mb:
        return False, f"low RAM: {free}MB free < {settings.brain_min_free_mb}MB floor"
    if reason := runtime_load.busy_reason(now=now):
        return False, reason
    if heavy_job_active(session, now=now):
        return False, "heavy job in flight — backing off"
    return True, f"ok: {free}MB free, no heavy job"
