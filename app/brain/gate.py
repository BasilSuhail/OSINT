"""The brain's resource gate (#409): may the model run right now?

Two cheap checks, no new dependency:
  1. RAM headroom — stdlib only (/proc/meminfo on Linux, vm_stat on macOS).
  2. No heavy job in flight — a job_runs row still `running` with a fresh
     heartbeat. That table already tracks every heavy analytical job; the
     I/O-bound fetchers deliberately don't use it, so it is a true
     "heavy work in progress" signal.

The second check yields to other work, which on a machine where other work
never stops means yielding forever, so it has a floor: `narrate_starved`.
"""

from __future__ import annotations

import platform
import subprocess
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brain import client
from app.db_models import BrainNarrativeRow, JobRunRow
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


#: Hosts that mean "the model loads in this same machine's memory".
_LOCAL_OLLAMA_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1", "", "0.0.0.0"})

#: `host.docker.internal` means one thing on Docker Desktop and the opposite on
#: native Linux Docker, and the difference decides whether a memory reading taken
#: in here describes the machine that will hold the model.
#:
#: Docker Desktop runs containers inside a virtual machine, so this name points at
#: a *different* machine and `/proc/meminfo` in here reports the VM's few
#: gigabytes rather than the host's. Native Linux Docker has no VM: the container
#: shares the host kernel, the name points at the same machine, and the reading is
#: exact.
#:
#: Treating it as remote everywhere switched the gate off on the machine it was
#: written for. A Raspberry Pi reached `qa_ram_blocked() -> False` for every ask,
#: loaded a 3.4 GB model into 8 GB already holding the stack and the console, and
#: locked up hard — twice — with the guard sitting right there returning False.
_REMOTE_VIA_DOCKER_HOSTS: frozenset[str] = frozenset(
    {"host.docker.internal", "gateway.docker.internal"}
)

#: Docker Desktop's VM runs a LinuxKit kernel; a Pi, a server and a desktop do
#: not. Read from inside the container, this is the one signal that says which of
#: the two situations above we are in, without asking the operator to declare it.
_DESKTOP_VM_KERNEL_MARKERS: tuple[str, ...] = ("linuxkit", "docker-desktop")


def in_docker_desktop_vm() -> bool:
    """Whether this process runs in Docker Desktop's virtual machine.

    A guess, and a load-bearing one, so `brain_same_machine_as_ollama` overrides
    it when the guess is wrong on some setup nobody here has seen.
    """
    declared = settings.brain_same_machine_as_ollama
    if declared is not None:
        return not declared
    release = platform.release().lower()
    return any(marker in release for marker in _DESKTOP_VM_KERNEL_MARKERS)


def ollama_is_local(url: str | None = None) -> bool:
    """Does Ollama run in the same memory as this process?

    The RAM floor only means something when it does. On the Pi and on bare
    metal the caller and the model share one machine, the check is exact, and
    that is what #409 was written against — it must not change there.

    Containerising the backend (#634) broke the assumption silently. The worker
    reads `/proc/meminfo` inside the Docker VM (2,983 MB total, ~1,026 MB
    available) while Ollama runs on the host over `host.docker.internal` with
    ~11 GB available. The brain refused to load a model on a machine with room
    to spare, because an unrelated machine was tight — and reported it as a
    successful run.
    """
    raw = url if url is not None else settings.ollama_url
    host = urlparse(raw).hostname or ""
    if host in _LOCAL_OLLAMA_HOSTS:
        return True
    #: The container-to-host name: same machine unless a VM sits between them.
    if host in _REMOTE_VIA_DOCKER_HOSTS:
        return not in_docker_desktop_vm()
    return False


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


def qa_ram_blocked() -> bool:
    """Should an ask be refused because the Q&A model will not fit?

    Same reasoning as `should_run`'s floor, and the same defect: the API is a
    container too, with a 512 MB ceiling of its own, reading the Docker VM's
    `/proc/meminfo`. Measured at 995 MB against a 3,800 MB floor — so every
    ask returned BRAIN_BUSY_ANSWER, always, while the host had ~11 GB free and
    Ollama sat idle. The floor is not merely too high there, it is larger than
    the VM's entire 2,983 MB, so no load could ever satisfy it.
    """
    if not ollama_is_local():
        return False
    #: A model already in memory needs no room to arrive in. The floor asks
    #: whether there is space to load one, which is not the question once it is
    #: loaded — and with one model serving every job, it usually is.
    if client.model_resident(settings.qa_model):
        return False
    return ram_free_mb() < settings.qa_min_free_mb


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


def narrate_starved(session: Session, *, now: datetime | None = None) -> bool:
    """Has the narrative gone unwritten for longer than the box may claim?

    A box that has never narrated is the starved case at its worst, not an
    exception to it: what the reader opens is empty either way.

    Asked in SQL rather than by reading a timestamp back out, because the
    heartbeat check next door already compares that way and a stored naive
    datetime would compare wrong here.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(minutes=settings.brain_narrate_starvation_minutes)
    row = session.execute(
        select(BrainNarrativeRow.id).where(BrainNarrativeRow.created_at >= cutoff).limit(1)
    ).first()
    return row is None


def should_run(
    session: Session, *, now: datetime | None = None, allow_when_starved: bool = False
) -> tuple[bool, str]:
    """(allowed, human reason). Reason powers the task log and the card's
    degraded state so backoff is visible, never a silent lie."""
    if not settings.brain_enabled:
        return False, "brain disabled (brain_enabled=false)"
    local = ollama_is_local()
    free = ram_free_mb() if local else None
    #: Same reasoning as the ask's floor: memory the model already occupies is
    #: not memory it still needs. On a small board one model does every job, so
    #: the first stage to run loads it and the rest were then refused for the
    #: space it was using — the situation summary skipped with "low RAM: 3057MB
    #: free < 3500MB floor" while the model sat resident and ready.
    resident = client.model_resident(settings.brain_model)
    if free is not None and not resident and free < settings.brain_min_free_mb:
        return False, f"low RAM: {free}MB free < {settings.brain_min_free_mb}MB floor"
    if reason := runtime_load.busy_reason(now=now):
        return False, reason
    if heavy_job_active(session, now=now):
        #: The escape from #409's backoff, and only for the caller that asks.
        #: The heavy beats on a busy board — clustering a backlog, grading
        #: headlines through a model, the checks that follow both — can run
        #: nose to tail for hours, and the beat that always yields to them
        #: never runs at all. The enrichment pass does not ask: a tag nobody
        #: has written is invisible, an empty console is not, and only one of
        #: them is worth loading a model into a box already working.
        if allow_when_starved and narrate_starved(session, now=now):
            return True, (
                "starved: no narrative in "
                f"{settings.brain_narrate_starvation_minutes}m — running "
                "despite the heavy job in flight"
            )
        return False, "heavy job in flight — backing off"
    if resident:
        return True, f"ok: {settings.brain_model} already loaded, no heavy job"
    if free is None:
        # Said plainly rather than reported as a passing RAM check: the floor
        # was not applied, and the reason should not imply otherwise.
        return True, f"ok: no heavy job (RAM floor not applied — Ollama at {settings.ollama_url})"
    return True, f"ok: {free}MB free, no heavy job"
