# Brain — Resource-Aware LLM + Situation Narrative Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the app a light local LLM that runs only when the box has headroom and narrates the current world signal + system state as a dashboard "Situation" card.

**Architecture:** A `brain_narrate` Celery beat task on the concurrency-1 `analytics` queue reads a compact snapshot of existing data and calls a small Ollama model with adaptive `keep_alive`. A resource gate (RAM headroom + no active heavy `job_run`) decides whether to run; heavy jobs evict the model on start via a hook in `job_run()`. Output is persisted (30-day retention) and served at `GET /brain/narrative/latest`.

**Tech Stack:** Python 3.14, SQLAlchemy + Alembic, Celery, FastAPI, httpx, Ollama (`qwen2.5:1.5b-instruct-q4_K_M`); Next.js + SWR + Tailwind + vitest on the frontend.

## Global Constraints

- **No new dependencies** — RAM read via stdlib (`/proc/meminfo` on Linux, `vm_stat` on macOS), never `psutil`. (Basil's rule.)
- **30-day retention** on all persisted data; enforced through the existing housekeeping job. (Storage rule.)
- **Localhost only** — the model is reached over `http://localhost:11434`; nothing leaves the machine.
- **No fabrication** — the narrative prompt describes only supplied numbers; temperature 0, `format:json`.
- **No Claude attribution** in commits or PRs. (Repo rule.)
- **Cross-dialect** — models/queries must run on Postgres (prod) and SQLite (tests); use `JsonColumn` and dialect-aware inserts as existing code does.
- **1 issue → 1 branch → 1 PR → 1 commit-family** — all work on `feat/brain-situation-narrative`, tracked on issue #409. Basil merges.

---

### Task 1: Settings + brain package + resource gate

**Files:**
- Modify: `app/settings.py:36` (add brain settings after `validator_batch_limit`)
- Create: `app/brain/__init__.py`
- Create: `app/brain/gate.py`
- Test: `tests/test_brain_gate.py`

**Interfaces:**
- Produces: `app/brain/gate.py`
  - `_parse_meminfo(text: str) -> int` — MB available from `/proc/meminfo` text
  - `_parse_vm_stat(text: str) -> int` — MB free+inactive from `vm_stat` text
  - `ram_free_mb() -> int` — platform dispatch
  - `heavy_job_active(session: Session, *, now: datetime | None = None) -> bool`
  - `should_run(session: Session, *, now: datetime | None = None) -> tuple[bool, str]`
- Produces (settings): `settings.brain_enabled: bool`, `settings.brain_model: str`, `settings.brain_min_free_mb: int`, `settings.brain_keep_alive: str`

- [ ] **Step 1: Add settings.** In `app/settings.py`, immediately after line 36 (`validator_batch_limit`):

```python
    # The brain (#409) — a light always-warm-when-idle local model, separate
    # from the 4b nightly validator above. Localhost only.
    brain_enabled: bool = Field(default=True)
    brain_model: str = Field(default="qwen2.5:1.5b-instruct-q4_K_M")
    # Refuse to load the model unless at least this much RAM is free (Pi guard).
    brain_min_free_mb: int = Field(default=1200)
    brain_keep_alive: str = Field(default="30m")
```

- [ ] **Step 2: Create `app/brain/__init__.py`** (empty package marker):

```python
"""The brain (#409): a resource-aware local LLM and the situation narrative."""
```

- [ ] **Step 3: Write the failing test** `tests/test_brain_gate.py`:

```python
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
    session.add(
        JobRunRow(job="cluster", status="running", heartbeat_at=now - timedelta(minutes=5))
    )
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
    allowed, reason = gate.should_run(session)
    assert allowed is True
```

- [ ] **Step 4: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_brain_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.brain.gate'`

- [ ] **Step 5: Implement `app/brain/gate.py`**

```python
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
from app.settings import settings

#: A job whose heartbeat is older than this is treated as dead, not busy.
_HEARTBEAT_FRESH_S: int = 90


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
        .where(JobRunRow.status == "running", JobRunRow.heartbeat_at >= cutoff)
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
    if heavy_job_active(session, now=now):
        return False, "heavy job in flight — backing off"
    return True, f"ok: {free}MB free, no heavy job"
```

- [ ] **Step 6: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_brain_gate.py -v`
Expected: PASS (7 tests)

- [ ] **Step 7: Format + lint**

Run: `.venv/bin/ruff format app/brain/ app/settings.py tests/test_brain_gate.py && .venv/bin/ruff check app/brain/`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add app/brain/__init__.py app/brain/gate.py app/settings.py tests/test_brain_gate.py
git commit -m "feat(brain): #409 resource gate — RAM headroom + heavy-job backoff"
```

---

### Task 2: Ollama client with adaptive keep-alive

**Files:**
- Create: `app/brain/client.py`
- Test: `tests/test_brain_client.py`

**Interfaces:**
- Consumes: `settings.brain_model`, `settings.brain_keep_alive`, `settings.ollama_url`
- Produces:
  - `generate_json(prompt: str, *, model: str | None = None, keep_alive: str | None = None) -> dict[str, Any]`
  - `evict(*, model: str | None = None) -> None` — unload via `keep_alive=0`

- [ ] **Step 1: Write the failing test** `tests/test_brain_client.py`:

```python
from typing import Any

import httpx

from app.brain import client


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


def test_generate_json_warm_keep_alive(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse({"response": '{"headline": "quiet"}'})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(client.settings, "brain_keep_alive", "30m")
    monkeypatch.setattr(client.settings, "brain_model", "qwen2.5:1.5b-instruct-q4_K_M")

    result = client.generate_json("hello")
    assert result == {"headline": "quiet"}
    assert captured["json"]["keep_alive"] == "30m"
    assert captured["json"]["model"] == "qwen2.5:1.5b-instruct-q4_K_M"
    assert captured["json"]["options"]["temperature"] == 0


def test_evict_sends_keep_alive_zero(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return _FakeResponse({"response": "{}"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client.evict()
    assert captured["json"]["keep_alive"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_brain_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.brain.client'`

- [ ] **Step 3: Implement `app/brain/client.py`**

```python
"""The brain's Ollama client (#409) — localhost HTTP via httpx, nothing leaves.

Same discipline as app/validator/client.py, but with an adaptive keep_alive so
the small model stays warm between the frequent narrate ticks, plus an evict()
that unloads it immediately (keep_alive=0) the moment a heavy job needs the RAM.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.settings import settings

_TIMEOUT_S: float = 120.0
_NUM_CTX: int = 2048


def generate_json(
    prompt: str, *, model: str | None = None, keep_alive: str | None = None
) -> dict[str, Any]:
    """One prompt → parsed JSON dict. Raises on HTTP or JSON failure."""
    response = httpx.post(
        f"{settings.ollama_url}/api/generate",
        json={
            "model": model or settings.brain_model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "think": False,
            "keep_alive": keep_alive or settings.brain_keep_alive,
            "options": {"temperature": 0, "num_ctx": _NUM_CTX},
        },
        timeout=_TIMEOUT_S,
    )
    response.raise_for_status()
    return json.loads(response.json()["response"])


def evict(*, model: str | None = None) -> None:
    """Unload the model now: an empty generate with keep_alive=0."""
    response = httpx.post(
        f"{settings.ollama_url}/api/generate",
        json={
            "model": model or settings.brain_model,
            "prompt": "",
            "stream": False,
            "keep_alive": 0,
        },
        timeout=_TIMEOUT_S,
    )
    response.raise_for_status()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_brain_client.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Format + lint + commit**

```bash
.venv/bin/ruff format app/brain/client.py tests/test_brain_client.py
.venv/bin/ruff check app/brain/client.py
git add app/brain/client.py tests/test_brain_client.py
git commit -m "feat(brain): #409 Ollama client — adaptive keep_alive + evict"
```

---

### Task 3: Eviction hook in job_run() (backoff when busy)

**Files:**
- Modify: `app/jobs/heartbeat.py:49-72` (the `job_run` signature + `_start`)
- Test: `tests/test_brain_eviction_hook.py`

**Interfaces:**
- Consumes: `app/brain/client.py::evict`, `settings.brain_enabled`
- Produces: `job_run(job, *, session_factory=None, evict_brain=True)` — new keyword. The brain's own task passes `evict_brain=False` so it does not evict itself.

- [ ] **Step 1: Write the failing test** `tests/test_brain_eviction_hook.py`:

```python
from app.jobs import heartbeat


def test_job_run_evicts_brain_on_start(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(heartbeat.settings, "brain_enabled", True)
    monkeypatch.setattr("app.brain.client.evict", lambda: calls.append("evict"))
    with heartbeat.job_run("cluster", session_factory=_fake_factory()):
        pass
    assert calls == ["evict"]


def test_job_run_skips_eviction_when_flag_false(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(heartbeat.settings, "brain_enabled", True)
    monkeypatch.setattr("app.brain.client.evict", lambda: calls.append("evict"))
    with heartbeat.job_run("brain-narrate", session_factory=_fake_factory(), evict_brain=False):
        pass
    assert calls == []


def test_job_run_swallows_evict_failure(monkeypatch):
    def boom():
        raise RuntimeError("ollama down")

    monkeypatch.setattr(heartbeat.settings, "brain_enabled", True)
    monkeypatch.setattr("app.brain.client.evict", boom)
    # must not raise — eviction is best-effort
    with heartbeat.job_run("cluster", session_factory=_fake_factory()):
        pass


def _fake_factory():
    """Minimal in-memory session factory for the heartbeat rows."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db_models import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_brain_eviction_hook.py -v`
Expected: FAIL — `TypeError: job_run() got an unexpected keyword argument 'evict_brain'`

- [ ] **Step 3: Implement the hook.** In `app/jobs/heartbeat.py`, change the `job_run` signature and add the eviction at the top of the body. Replace lines 49-58 (the signature through `factory = ...`):

```python
@contextmanager
def job_run(
    job: str,
    *,
    session_factory: SessionFactory | None = None,
    evict_brain: bool = True,
) -> Iterator[Callable[[str], None]]:
    """Record one job execution; yields a `progress(text)` heartbeat function.

    Exceptions mark the row failed (with truncated detail) and re-raise —
    the job's own error handling stays untouched.

    On start, best-effort evicts the brain model (#409) so a heavy job
    reclaims its RAM before the work begins. The brain's own narrate task
    passes ``evict_brain=False`` so it never evicts itself.
    """
    from app.settings import settings

    if evict_brain and settings.brain_enabled:
        try:
            from app.brain.client import evict

            evict()
        except Exception:  # best-effort: the brain must never break a real job
            pass

    factory = session_factory or _default_factory()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_brain_eviction_hook.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full existing heartbeat/job suite to prove no regression**

Run: `.venv/bin/pytest tests/ -k "heartbeat or job_run or validator_task" -q`
Expected: PASS (existing tests unaffected — eviction is guarded and best-effort)

- [ ] **Step 6: Format + lint + commit**

```bash
.venv/bin/ruff format app/jobs/heartbeat.py tests/test_brain_eviction_hook.py
.venv/bin/ruff check app/jobs/heartbeat.py
git add app/jobs/heartbeat.py tests/test_brain_eviction_hook.py
git commit -m "feat(brain): #409 evict brain on heavy-job start; self-exempt narrate"
```

---

### Task 4: brain_narrative table + migration

**Files:**
- Modify: `app/db_models.py` (add `BrainNarrativeRow` after `StoryReviewRow`, ~line 434+)
- Create: `migrations/versions/0014_brain_narrative.py`
- Test: `tests/test_brain_narrative_model.py`

**Interfaces:**
- Produces: `BrainNarrativeRow` with columns `id, created_at, model, payload (JSON), input_digest`

- [ ] **Step 1: Write the failing test** `tests/test_brain_narrative_model.py`:

```python
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db_models import Base, BrainNarrativeRow


def test_brain_narrative_roundtrip():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            BrainNarrativeRow(
                created_at=datetime(2026, 7, 12, tzinfo=UTC),
                model="qwen2.5:1.5b-instruct-q4_K_M",
                payload={"headline": "quiet", "watch": []},
                input_digest="sha256:abc",
            )
        )
        session.commit()
        row = session.execute(select(BrainNarrativeRow)).scalar_one()
        assert row.payload["headline"] == "quiet"
        assert row.input_digest == "sha256:abc"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_brain_narrative_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'BrainNarrativeRow'`

- [ ] **Step 3: Add the model.** Append to `app/db_models.py` (after `StoryReviewRow`):

```python
class BrainNarrativeRow(Base):
    """One situation narrative produced by the brain (#409).

    Append-only, 30-day retention (housekeeping prunes it). `input_digest`
    lets a reader tell a genuinely new narrative from a mere re-render.
    """

    __tablename__ = "brain_narrative"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JsonColumn, nullable=False)
    input_digest: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("brain_narrative_created_idx", "created_at"),)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_brain_narrative_model.py -v`
Expected: PASS

- [ ] **Step 5: Create the migration** `migrations/versions/0014_brain_narrative.py`:

```python
"""Brain situation narrative (#409).

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brain_narrative",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("input_digest", sa.Text, nullable=False),
    )
    op.create_index("brain_narrative_created_idx", "brain_narrative", ["created_at"])


def downgrade() -> None:
    op.drop_index("brain_narrative_created_idx", table_name="brain_narrative")
    op.drop_table("brain_narrative")
```

- [ ] **Step 6: Verify the migration applies against a scratch SQLite DB**

Run: `.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head`
Expected: three clean runs, no error (uses the configured DB; if only Postgres is configured, run against the live dev Postgres from `make start`).

- [ ] **Step 7: Format + lint + commit**

```bash
.venv/bin/ruff format app/db_models.py migrations/versions/0014_brain_narrative.py tests/test_brain_narrative_model.py
.venv/bin/ruff check app/db_models.py migrations/versions/0014_brain_narrative.py
git add app/db_models.py migrations/versions/0014_brain_narrative.py tests/test_brain_narrative_model.py
git commit -m "feat(brain): #409 brain_narrative table + migration 0014"
```

---

### Task 5: Snapshot context builder + prompt

**Files:**
- Create: `app/brain/context.py`
- Test: `tests/test_brain_context.py`

**Interfaces:**
- Consumes: `StoryRow`, `JobRunRow`, `IngestHealthRow`
- Produces:
  - `build_snapshot(session: Session, *, now: datetime | None = None) -> dict[str, Any]`
  - `input_digest(snapshot: dict[str, Any]) -> str` — `"sha256:<hex>"`
  - `build_prompt(snapshot: dict[str, Any]) -> str`

- [ ] **Step 1: Write the failing test** `tests/test_brain_context.py`:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.brain import context
from app.db_models import Base, JobRunRow, StoryRow


def _session_with_data(now):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        StoryRow(
            title="Border clashes reported",
            first_seen=now - timedelta(hours=3),
            last_seen=now,
            member_count=12,
            outlet_count=7,
            owner_count=3,
            method_version="stories-v1.0",
        )
    )
    session.add(JobRunRow(job="cluster_stories", status="done", heartbeat_at=now))
    session.add(JobRunRow(job="compute_composite", status="failed", heartbeat_at=now))
    session.commit()
    return session


def test_build_snapshot_has_core_sections():
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    session = _session_with_data(now)
    snap = context.build_snapshot(session, now=now)
    assert snap["top_stories"][0]["title"] == "Border clashes reported"
    assert snap["jobs"]["failed"] == 1
    assert "as_of" in snap


def test_input_digest_is_stable_and_prefixed():
    snap = {"top_stories": [], "jobs": {}, "as_of": "x"}
    d1 = context.input_digest(snap)
    d2 = context.input_digest(dict(snap))
    assert d1 == d2
    assert d1.startswith("sha256:")


def test_build_prompt_is_bounded():
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    session = _session_with_data(now)
    prompt = context.build_prompt(context.build_snapshot(session, now=now))
    assert "headline" in prompt  # asks for the schema
    assert len(prompt) < 6000  # stays well inside num_ctx 2048
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_brain_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.brain.context'`

- [ ] **Step 3: Implement `app/brain/context.py`**

```python
"""The brain's snapshot builder (#409).

Feeds the model pre-digested numbers, never raw rows, so the prompt stays tiny
(num_ctx 2048) and cheap on the Pi. The snapshot spans the world signal (top
stories) and the system itself (job outcomes, ingest freshness).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db_models import IngestHealthRow, JobRunRow, StoryRow

_TOP_STORIES: int = 5
_STORY_WINDOW_H: int = 24
_JOB_WINDOW_H: int = 6


def build_snapshot(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    story_cut = now - timedelta(hours=_STORY_WINDOW_H)
    job_cut = now - timedelta(hours=_JOB_WINDOW_H)

    stories = session.execute(
        select(StoryRow)
        .where(StoryRow.last_seen >= story_cut)
        .order_by(StoryRow.outlet_count.desc(), StoryRow.member_count.desc())
        .limit(_TOP_STORIES)
    ).scalars().all()

    job_counts = dict(
        session.execute(
            select(JobRunRow.status, func.count())
            .where(JobRunRow.started_at >= job_cut)
            .group_by(JobRunRow.status)
        ).all()
    )

    freshest = session.execute(
        select(func.max(IngestHealthRow.checked_at))
    ).scalar_one_or_none()

    return {
        "as_of": now.isoformat(),
        "top_stories": [
            {
                "title": s.title,
                "outlets": s.outlet_count,
                "members": s.member_count,
            }
            for s in stories
        ],
        "jobs": {
            "done": int(job_counts.get("done", 0)),
            "running": int(job_counts.get("running", 0)),
            "failed": int(job_counts.get("failed", 0)),
        },
        "ingest_last_check": freshest.isoformat() if freshest else None,
    }


def input_digest(snapshot: dict[str, Any]) -> str:
    blob = json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def build_prompt(snapshot: dict[str, Any]) -> str:
    return (
        "You are the situational-awareness brain of an OSINT early-warning "
        "system. Below is a JSON snapshot of the current world signal and the "
        "system's own health. Describe ONLY what the numbers show. Invent no "
        "facts, names, places, or events not present in the snapshot.\n\n"
        "Return a JSON object with exactly these keys:\n"
        '  "headline": one short sentence, the single most important thing now.\n'
        '  "world": 2-4 sentences on the story signal.\n'
        '  "system": 1-2 sentences on pipeline health (jobs, ingest freshness).\n'
        '  "watch": array of 0-3 short strings to keep an eye on.\n\n'
        f"SNAPSHOT:\n{json.dumps(snapshot, ensure_ascii=False)}"
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_brain_context.py -v`
Expected: PASS (3 tests)

> **Note for the implementer:** confirm `IngestHealthRow` has a `checked_at` column before running (it is defined in `app/db_models.py`). If the column is named differently (e.g. `fetched_at`), use that name in the `freshest` query and the test stays green because it only checks `top_stories`/`jobs`.

- [ ] **Step 5: Format + lint + commit**

```bash
.venv/bin/ruff format app/brain/context.py tests/test_brain_context.py
.venv/bin/ruff check app/brain/context.py
git add app/brain/context.py tests/test_brain_context.py
git commit -m "feat(brain): #409 snapshot context builder + narrative prompt"
```

---

### Task 6: Narrate task body, beat schedule, routing, make target

**Files:**
- Create: `app/brain/task.py`
- Create: `app/brain/run.py` (for `make brain`)
- Modify: `app/tasks.py` (add `brain_narrate` task + beat entry)
- Modify: `app/celery_app.py:38-48` (route `brain_narrate` to `analytics`)
- Modify: `Makefile` (add `brain` target)
- Test: `tests/test_brain_task.py`

**Interfaces:**
- Consumes: `gate.should_run`, `context.build_snapshot/input_digest/build_prompt`, `client.generate_json`, `BrainNarrativeRow`, `job_run`
- Produces: `_narrate_body(*, now=None) -> dict[str, Any]` and Celery task `app.tasks.brain_narrate`

- [ ] **Step 1: Write the failing test** `tests/test_brain_task.py`:

```python
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.brain import task as brain_task
from app.db_models import Base, BrainNarrativeRow


def _factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def test_narrate_persists_row_when_allowed(monkeypatch):
    factory = _factory()
    monkeypatch.setattr(brain_task, "_session_factory", lambda: factory)
    monkeypatch.setattr(brain_task.gate, "should_run", lambda session, now=None: (True, "ok"))
    monkeypatch.setattr(
        brain_task.client,
        "generate_json",
        lambda prompt: {"headline": "quiet", "world": "w", "system": "s", "watch": []},
    )
    result = brain_task._narrate_body(now=datetime(2026, 7, 12, tzinfo=UTC))
    assert result["persisted"] is True
    with factory() as session:
        row = session.execute(select(BrainNarrativeRow)).scalar_one()
        assert row.payload["headline"] == "quiet"


def test_narrate_skips_when_gated(monkeypatch):
    factory = _factory()
    monkeypatch.setattr(brain_task, "_session_factory", lambda: factory)
    monkeypatch.setattr(
        brain_task.gate, "should_run", lambda session, now=None: (False, "low RAM")
    )
    result = brain_task._narrate_body(now=datetime(2026, 7, 12, tzinfo=UTC))
    assert result["persisted"] is False
    assert result["reason"] == "low RAM"
    with factory() as session:
        assert session.execute(select(BrainNarrativeRow)).first() is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_brain_task.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.brain.task'`

- [ ] **Step 3: Implement `app/brain/task.py`**

```python
"""The brain's narrate worker body (#409).

Gated by resource headroom; when allowed, builds the snapshot, asks the small
model to narrate it, and persists one row. Runs inside job_run with
evict_brain=False so it never evicts the very model it is about to use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.brain import client, context, gate
from app.db_models import BrainNarrativeRow
from app.db import get_engine
from app.settings import settings

#: The four keys the prompt asks for; anything else the model adds is dropped.
_KEYS = ("headline", "world", "system", "watch")


def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def _narrate_body(*, now: datetime | None = None) -> dict[str, Any]:
    from app.jobs.heartbeat import job_run

    now = now or datetime.now(UTC)
    factory = _session_factory()
    with job_run("brain-narrate", session_factory=factory, evict_brain=False):
        with factory() as session:
            allowed, reason = gate.should_run(session, now=now)
            if not allowed:
                return {"persisted": False, "reason": reason}

            snapshot = context.build_snapshot(session, now=now)
            raw = client.generate_json(context.build_prompt(snapshot))
            payload = {key: raw.get(key) for key in _KEYS}

            session.add(
                BrainNarrativeRow(
                    created_at=now,
                    model=settings.brain_model,
                    payload=payload,
                    input_digest=context.input_digest(snapshot),
                )
            )
            session.commit()
            return {"persisted": True, "reason": reason}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_brain_task.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Register the Celery task.** In `app/tasks.py`, add near the other `@app.task` bodies (after `weekly_briefing`, ~line 200). First add the import at the top with the other body imports (near line 38 `from app.validator.task import _validator_body`):

```python
from app.brain.task import _narrate_body
```

Then the task:

```python
@app.task(
    name="app.tasks.brain_narrate",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def brain_narrate() -> dict[str, Any]:
    """The brain (#409): narrate the world signal + system state when the box
    has headroom. Gated; a busy box simply skips and leaves the last narrative."""
    return _narrate_body()
```

- [ ] **Step 6: Add the beat entry.** In `app/tasks.py`, inside `app.conf.beat_schedule = { ... }`, add alongside the others:

```python
    # The brain narrates every 15 min when the box is idle enough (#409).
    "brain-narrate-15min": {
        "task": "app.tasks.brain_narrate",
        "schedule": crontab(minute="*/15"),
    },
```

- [ ] **Step 7: Route it to the analytics queue.** In `app/celery_app.py`, add `"app.tasks.brain_narrate",` to the tuple in `task_routes` (after `"app.tasks.run_housekeeping",`):

```python
        "app.tasks.run_housekeeping",
        "app.tasks.brain_narrate",
```

- [ ] **Step 8: Create `app/brain/run.py`** (one-shot for `make brain`):

```python
"""Run the brain narrate once — `make brain` / `python -m app.brain.run`."""

from __future__ import annotations

from app.brain.task import _narrate_body


def main() -> None:
    result = _narrate_body()
    print(result)


if __name__ == "__main__":
    main()
```

- [ ] **Step 9: Add the Makefile target.** In `Makefile`, after the `validator` target (line 73), add and append `brain` to `.PHONY`:

```makefile
brain:  ## Run the brain narrate once — needs Ollama + qwen2.5:1.5b (#409)
	.venv/bin/python -m app.brain.run
```

- [ ] **Step 10: Verify the beat schedule + routing import cleanly**

Run: `.venv/bin/python -c "import app.tasks, app.celery_app; print('brain-narrate-15min' in app.tasks.app.conf.beat_schedule); print(app.celery_app.app.conf.task_routes['app.tasks.brain_narrate'])"`
Expected: `True` then `{'queue': 'analytics'}`

- [ ] **Step 11: Format + lint + commit**

```bash
.venv/bin/ruff format app/brain/task.py app/brain/run.py app/tasks.py app/celery_app.py tests/test_brain_task.py
.venv/bin/ruff check app/brain/ app/tasks.py app/celery_app.py
git add app/brain/task.py app/brain/run.py app/tasks.py app/celery_app.py Makefile tests/test_brain_task.py
git commit -m "feat(brain): #409 narrate task — beat every 15m, analytics queue, make brain"
```

---

### Task 7: API endpoint /brain/narrative/latest

**Files:**
- Modify: `app/api.py` (add endpoint; add `BrainNarrativeRow` to the `app.db_models` import block at line 22)
- Test: `tests/test_brain_api.py`

**Interfaces:**
- Consumes: `BrainNarrativeRow`, `get_session`
- Produces: `GET /brain/narrative/latest` → `{"present": bool, "payload": dict | None, "model": str | None, "created_at": str | None}`

- [ ] **Step 1: Write the failing test** `tests/test_brain_api.py`:

```python
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api import app, get_session
from app.db_models import Base, BrainNarrativeRow


def _client_with_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override
    return TestClient(app), factory


def test_latest_empty_when_none():
    client, _ = _client_with_db()
    body = client.get("/brain/narrative/latest").json()
    assert body["present"] is False
    assert body["payload"] is None
    app.dependency_overrides.clear()


def test_latest_returns_newest():
    client, factory = _client_with_db()
    with factory() as session:
        session.add(
            BrainNarrativeRow(
                created_at=datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
                model="qwen2.5:1.5b-instruct-q4_K_M",
                payload={"headline": "quiet"},
                input_digest="sha256:a",
            )
        )
        session.commit()
    body = client.get("/brain/narrative/latest").json()
    assert body["present"] is True
    assert body["payload"]["headline"] == "quiet"
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_brain_api.py -v`
Expected: FAIL — 404 (route not defined) / `KeyError`

- [ ] **Step 3: Add `BrainNarrativeRow` to the imports** in `app/api.py` (inside the `from app.db_models import (` block at line 22), then add the endpoint (place it near the other read endpoints, e.g. after `/jobs/recent`):

```python
@app.get("/brain/narrative/latest")
def brain_narrative_latest(session: Session = Depends(get_session)) -> dict:
    """The newest situation narrative (#409), or an explicit empty shape.

    The frontend uses `created_at` to decide when to render the card as stale
    ("brain resting") — backoff is visible, never a silent lie.
    """
    row = session.execute(
        select(BrainNarrativeRow).order_by(BrainNarrativeRow.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        return {"present": False, "payload": None, "model": None, "created_at": None}
    return {
        "present": True,
        "payload": row.payload,
        "model": row.model,
        "created_at": row.created_at.isoformat(),
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_brain_api.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Format + lint + commit**

```bash
.venv/bin/ruff format app/api.py tests/test_brain_api.py
.venv/bin/ruff check app/api.py
git add app/api.py tests/test_brain_api.py
git commit -m "feat(brain): #409 GET /brain/narrative/latest"
```

---

### Task 8: 30-day retention for brain_narrative

**Files:**
- Modify: `app/housekeeping.py` (add a prune helper + call it from `run_retention_and_cap`)
- Test: `tests/test_brain_retention.py`

**Interfaces:**
- Consumes: `BrainNarrativeRow`, `settings.retention_news_days` (reuse the 30-day window)
- Produces: `prune_brain_narrative(session, *, now=None) -> int`

- [ ] **Step 1: Write the failing test** `tests/test_brain_retention.py`:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db_models import Base, BrainNarrativeRow
from app.housekeeping import prune_brain_narrative


def test_prune_deletes_rows_older_than_30_days():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 12, tzinfo=UTC)
    with Session(engine) as session:
        session.add(
            BrainNarrativeRow(
                created_at=now - timedelta(days=31),
                model="m",
                payload={},
                input_digest="sha256:old",
            )
        )
        session.add(
            BrainNarrativeRow(
                created_at=now - timedelta(days=1),
                model="m",
                payload={},
                input_digest="sha256:new",
            )
        )
        session.commit()
        deleted = prune_brain_narrative(session, now=now)
        session.commit()
        assert deleted == 1
        remaining = session.execute(select(BrainNarrativeRow.input_digest)).scalars().all()
        assert remaining == ["sha256:new"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_brain_retention.py -v`
Expected: FAIL — `ImportError: cannot import name 'prune_brain_narrative'`

- [ ] **Step 3: Implement.** In `app/housekeeping.py`, add the import for `BrainNarrativeRow` (with the other `db_models` imports) and the helper, then call it inside `run_retention_and_cap` (add a line where the other prunes run):

```python
def prune_brain_narrative(session: Session, *, now: datetime | None = None) -> int:
    """Delete situation narratives older than the news retention window (#409)."""
    from app.db_models import BrainNarrativeRow

    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.retention_news_days)
    result = session.execute(
        delete(BrainNarrativeRow).where(BrainNarrativeRow.created_at < cutoff)
    )
    return result.rowcount or 0
```

Then, inside `run_retention_and_cap(session)`, after the events prune runs, add:

```python
    brain_deleted = prune_brain_narrative(session, now=now)
    result["brain_narrative"] = brain_deleted
```

> **Note for the implementer:** open `run_retention_and_cap` and match the local variable names in scope (`now`, `result`/the returned dict). If `now` is not in scope there, call `prune_brain_narrative(session)`.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_brain_retention.py -v`
Expected: PASS

- [ ] **Step 5: Run the housekeeping suite to prove no regression**

Run: `.venv/bin/pytest tests/ -k housekeeping -q`
Expected: PASS

- [ ] **Step 6: Format + lint + commit**

```bash
.venv/bin/ruff format app/housekeeping.py tests/test_brain_retention.py
.venv/bin/ruff check app/housekeeping.py
git add app/housekeeping.py tests/test_brain_retention.py
git commit -m "feat(brain): #409 30-day retention for brain_narrative"
```

---

### Task 9: Frontend — fetcher, Situation card, deck registration

**Files:**
- Modify: `osint-frontend/lib/apiClient.ts` (add `fetchBrainNarrative`)
- Create: `osint-frontend/components/panels/SituationPanel.tsx`
- Modify: `osint-frontend/components/SplitLayout.tsx` (import + register card)
- Test: `osint-frontend/lib/brainNarrative.test.mts`

**Interfaces:**
- Consumes: `API_BASE` from `apiClient.ts`
- Produces: `fetchBrainNarrative(): Promise<BrainNarrative>` where
  `BrainNarrative = { present: boolean; payload: { headline?: string; world?: string; system?: string; watch?: string[] } | null; model: string | null; created_at: string | null }`

- [ ] **Step 1: Write the failing test** `osint-frontend/lib/brainNarrative.test.mts`:

```typescript
import { describe, expect, it, vi, afterEach } from "vitest"
import { fetchBrainNarrative } from "./apiClient"

afterEach(() => vi.restoreAllMocks())

describe("fetchBrainNarrative", () => {
  it("returns the parsed narrative", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          present: true,
          payload: { headline: "quiet", watch: [] },
          model: "qwen2.5:1.5b-instruct-q4_K_M",
          created_at: "2026-07-12T12:00:00+00:00",
        }),
      })),
    )
    const out = await fetchBrainNarrative()
    expect(out.present).toBe(true)
    expect(out.payload?.headline).toBe("quiet")
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd osint-frontend && pnpm test brainNarrative`
Expected: FAIL — `fetchBrainNarrative` is not exported

- [ ] **Step 3: Add the fetcher + type** to `osint-frontend/lib/apiClient.ts` (end of file):

```typescript
export interface BrainNarrative {
  present: boolean
  payload: {
    headline?: string
    world?: string
    system?: string
    watch?: string[]
  } | null
  model: string | null
  created_at: string | null
}

export async function fetchBrainNarrative(): Promise<BrainNarrative> {
  const res = await fetch(`${API_BASE}/brain/narrative/latest`)
  if (!res.ok) throw new Error(`brain narrative ${res.status}`)
  return (await res.json()) as BrainNarrative
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd osint-frontend && pnpm test brainNarrative`
Expected: PASS

- [ ] **Step 5: Create `osint-frontend/components/panels/SituationPanel.tsx`**

```tsx
"use client"

/**
 * The Situation card (#409) — the brain's plain-English read on the world
 * signal and the system's own health. Refreshes every 5 min; renders a
 * visible "resting" state when the brain has backed off (no narrative, or a
 * stale one) so backoff is honest, never hidden.
 */

import useSWR from "swr"
import { fetchBrainNarrative } from "@/lib/apiClient"

const REFRESH_MS = 5 * 60_000
//: Older than this and the card says the brain is resting.
const STALE_MS = 40 * 60_000

export function SituationPanel() {
  const { data } = useSWR("brain-narrative", fetchBrainNarrative, {
    refreshInterval: REFRESH_MS,
  })

  const narrative = data?.payload ?? null
  const createdAt = data?.created_at ? new Date(data.created_at).getTime() : 0
  const stale = !data?.present || Date.now() - createdAt > STALE_MS

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3 text-neutral-100">
      <header className="flex items-center justify-between">
        <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-500">
          situation — the brain
        </p>
        {data?.model ? (
          <span className="font-mono text-[9px] text-neutral-600">{data.model}</span>
        ) : null}
      </header>

      {stale ? (
        <p className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3 text-sm text-neutral-400">
          Brain resting — the box is busy or no read is ready yet. Last narrative
          {data?.created_at ? ` from ${new Date(data.created_at).toLocaleTimeString()}` : " unavailable"}.
        </p>
      ) : null}

      {narrative ? (
        <>
          <h2 className="text-lg font-semibold leading-snug">{narrative.headline}</h2>
          {narrative.world ? <p className="text-sm text-neutral-300">{narrative.world}</p> : null}
          {narrative.system ? (
            <p className="text-sm text-neutral-400">{narrative.system}</p>
          ) : null}
          {narrative.watch && narrative.watch.length > 0 ? (
            <ul className="list-disc pl-5 text-sm text-neutral-300">
              {narrative.watch.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
```

- [ ] **Step 6: Register the card** in `osint-frontend/components/SplitLayout.tsx`. Add the import next to the other panel imports (near line 13):

```tsx
import { SituationPanel } from "./panels/SituationPanel"
```

Then add it as the first entry of the `deckCards` array (before `briefing`, ~line 101):

```tsx
    { key: "situation", title: "situation", content: <SituationPanel /> },
```

- [ ] **Step 7: Typecheck + run the frontend test suite**

Run: `cd osint-frontend && pnpm test brainNarrative && pnpm exec tsc --noEmit`
Expected: PASS + no type errors

- [ ] **Step 8: Commit**

```bash
git add osint-frontend/lib/apiClient.ts osint-frontend/lib/brainNarrative.test.mts osint-frontend/components/panels/SituationPanel.tsx osint-frontend/components/SplitLayout.tsx
git commit -m "feat(brain): #409 Situation card — brain narrative with visible resting state"
```

---

### Task 10: README Chapter 4 (the brain) + Chapter 5 renumber

**Files:**
- Modify: `README.md` (chapters index line 9-12; renumber current Ch4 → Ch5; insert new Ch4)

**Interfaces:** documentation only.

- [ ] **Step 1: Update the chapters index** (`README.md` lines 9-12). Replace the block with:

```markdown
- [Chapter 1 — Switch it on](#chapter-1--switch-it-on)
- [Chapter 2 — Can we trust the data?](#chapter-2--can-we-trust-the-data)
- [Chapter 3 — How the data gets collected](#chapter-3--how-the-data-gets-collected)
- [Chapter 4 — The brain](#chapter-4--the-brain)
- [Chapter 5 — How to read the dashboard](#chapter-5--how-to-read-the-dashboard)
```

- [ ] **Step 2: Renumber the current dashboard chapter.** Find the heading `# Chapter 4 — How to read the dashboard` (line ~390) and change it to:

```markdown
# Chapter 5 — How to read the dashboard
```

- [ ] **Step 3: Insert the new Chapter 4** immediately before `# Chapter 5 — How to read the dashboard`:

```markdown
# Chapter 4 — The brain

The system has a small local brain: a light model (`qwen2.5:1.5b-instruct-q4_K_M`,
~1 GB) that runs **only when the box has headroom** and narrates what is going on —
both the world signal and the pipeline itself.

### 4.1 Why it isn't always resident

Production is an 8 GB Raspberry Pi. A model pinned in RAM 24/7 would fight scraping
and the analytical batch and OOM the Pi. So the brain uses **adaptive keep-alive**:
warm during idle windows, **evicted the instant a heavy job starts**, reloaded when
the box goes quiet again. The eviction is wired into `job_run()` — every heavy job
passes through it, so the model always steps aside *before* the pandas parse grabs
memory. A resource gate (`app/brain/gate.py`) also refuses to load unless there is
enough free RAM and no heavy job is already running.

### 4.2 What it produces

Every ~15 minutes, when the gate allows, the brain reads a compact snapshot (top
stories, job outcomes, ingest freshness) and writes a short JSON narrative:

- **headline** — the single most important thing right now
- **world** — 2-4 sentences on the story signal
- **system** — 1-2 sentences on pipeline health
- **watch** — a few things to keep an eye on

It describes **only the numbers it is given** — same no-fabrication discipline as the
validator. It never invents facts.

### 4.3 Expected vs actual output

Expected shape (`GET /brain/narrative/latest`):

```json
{
  "present": true,
  "model": "qwen2.5:1.5b-instruct-q4_K_M",
  "created_at": "2026-07-12T12:00:00+00:00",
  "payload": {
    "headline": "Border-clash coverage is the loudest signal; pipeline healthy.",
    "world": "Seven outlets are carrying a border-clashes story across twelve members. No other cluster is close in reach.",
    "system": "All six analytical jobs completed in the last hour; ingest last checked two minutes ago.",
    "watch": ["Whether the border story keeps gaining outlets", "The failed composite job from earlier"]
  }
}
```

When the box is busy, the brain steps aside; `GET /brain/narrative/latest` simply
returns the last narrative and the **Situation card renders "brain resting"** so the
backoff is visible.

### 4.4 Running it

```bash
ollama pull qwen2.5:1.5b-instruct-q4_K_M   # one time
make brain                                 # run one narration now
```

The nightly validator keeps its own 4b model; the brain is separate and lighter.
Turn the brain off entirely with `BRAIN_ENABLED=false` in `.env`.

```

- [ ] **Step 4: Verify the anchors resolve.** Confirm no other heading still says "Chapter 4 — How to read" and the two new anchors match:

Run: `grep -n "Chapter 4\|Chapter 5\|# Chapter" README.md`
Expected: index shows Ch4 "The brain" + Ch5 "How to read the dashboard"; body has `# Chapter 4 — The brain` and `# Chapter 5 — How to read the dashboard`, and no leftover `# Chapter 4 — How to read`.

- [ ] **Step 5: Check for stale in-body cross-references.** Search the body for phrases that pointed at "Chapter 4" meaning the dashboard chapter and update any to "Chapter 5":

Run: `grep -n "Chapter 4" README.md`
Expected: only the brain references remain; fix any that meant the dashboard chapter.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs(brain): #409 README ch4 'The brain'; dashboard chapter -> ch5"
```

---

### Task 11: Verify end-to-end + PR + issue log

**Files:** none (integration + reporting)

- [ ] **Step 1: Full backend test sweep**

Run: `.venv/bin/pytest tests/ -q`
Expected: all pass (new brain tests + no regressions)

- [ ] **Step 2: Lint + format gates (CI parity)**

Run: `.venv/bin/ruff format --check . && .venv/bin/ruff check .`
Expected: clean (backend CI runs both — see `osint-ci-verify-gates`)

- [ ] **Step 3: Live smoke (requires Ollama + model pulled).** With `make start` running:

Run: `ollama pull qwen2.5:1.5b-instruct-q4_K_M && make brain && curl -s http://localhost:8000/brain/narrative/latest`
Expected: `make brain` prints `{'persisted': True, ...}`; the curl returns a narrative with a non-empty `headline`. If Ollama is down, `make brain` prints `persisted: False` with a reason and the API returns the empty shape — confirm that degradation is clean.

- [ ] **Step 4: Push the branch + open the PR** (links #409):

```bash
git push -u origin feat/brain-situation-narrative
gh pr create --title "feat(brain): resource-aware local LLM + situation narrative (Phase 1)" \
  --body "Closes #409. Phase 1 of the brain: a light local model (qwen2.5:1.5b) kept warm only when the box has headroom, evicted the instant a heavy job starts, narrating the world signal + system state into a Situation card. Design: docs/superpowers/specs/2026-07-12-brain-situation-narrative-design.md."
```

- [ ] **Step 5: Post the closing progress comment on #409** summarizing what shipped, the model to pull, and that Phase 2 (Q&A) / Phase 3 (enrichment) remain deferred. (Basil merges the PR.)

---

## Self-Review

**Spec coverage:**
- §4 architecture (beat task on analytics queue) → Task 6. ✓
- §5.1 gate → Task 1. ✓
- §5.2 client adaptive keep-alive → Task 2. ✓
- §5.3 eviction hook + self-exempt → Task 3. ✓
- §5.4 settings → Task 1 Step 1. ✓
- §6.1 context builder → Task 5. ✓
- §6.2 payload shape → Task 5 (prompt) + Task 6 (`_KEYS`). ✓
- §6.3 beat task + cadence → Task 6. ✓
- §6.4 storage + retention → Task 4 (table) + Task 8 (prune). ✓
- §6.5 API + Situation card + degraded state → Task 7 + Task 9. ✓
- §8 error handling / degradation → Task 6 (gated skip), Task 3 (best-effort evict), Task 11 Step 3 (smoke). ✓
- §9 tests → each task is TDD. ✓
- §10 README ch4 + ch5 renumber → Task 10. ✓
- §11 deliverables checklist → covered; PR + issue log in Task 11. ✓

**Placeholder scan:** No TBD/TODO; two "Note for the implementer" callouts (context column name, housekeeping local names) point at a concrete verification, not deferred work.

**Type consistency:** `should_run(session, *, now)` used identically in gate, task, and tests. `generate_json(prompt, *, model, keep_alive)` and `evict()` consistent across client, task, hook. `BrainNarrativeRow(created_at, model, payload, input_digest)` identical in model, migration, task, api, retention. `fetchBrainNarrative()`/`BrainNarrative` consistent across apiClient + panel + test. `evict_brain` keyword consistent in heartbeat + narrate task.
