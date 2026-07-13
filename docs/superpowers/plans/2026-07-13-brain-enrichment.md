# Brain Phase 3 — Story Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each new story a timely one-line gist + two enum tags from the 1.5b brain, on idle windows, surfaced on the Stories card.

**Architecture:** An idle-gated `brain_enrich` Celery beat task (analytics queue, batch-capped) gists window stories that lack one, using the Phase 1 brain client and gate, storing to a new `story_gist` table (idempotent per story+method version, 30-day retention). Gist joins onto `/stories/top` and shows on the Stories card. The Phase 1 gate self-exemption is generalized to all `brain-` jobs so enrich doesn't self-block.

**Tech Stack:** Python 3.14, SQLAlchemy + Alembic, Celery, FastAPI, httpx, Ollama (`qwen2.5:1.5b-instruct-q4_K_M`); Next.js + SWR + Tailwind + vitest.

## Global Constraints

- **No new dependencies.**
- **Reuse Phase 1/validator patterns verbatim:** `app/brain/client.generate_json`, `app/brain/gate.should_run`, `app/jobs/heartbeat.job_run` (with `evict_brain=False`), the validator's member-title query and dialect-aware idempotent insert (`app/validator/task.py`), `app.stories.task.WINDOW_HOURS`.
- **30-day retention** via housekeeping, like `brain_narrative`.
- **No-fabrication:** the gist prompt describes only the supplied headlines; temperature 0, `format:json`.
- **Fixed enums:** `category ∈ {conflict, economy, disaster, politics, other}`, `escalating ∈ {yes, no, unclear}`; off-enum/missing → `other`/`unclear` — never an invalid value in the DB.
- **Cross-dialect** (Postgres prod, SQLite tests); dialect-aware inserts + `LIKE` that works on both.
- **CI lints `app/ tests/`** with BOTH `ruff check` and `ruff format --check`; run both on changed files before each commit (watch RUF059 in tests).
- **No Claude attribution** in commits or the PR body.
- **1 issue (#413) → 1 branch (`feat/brain-enrichment`) → 1 PR.** Basil merges.

---

### Task 1: Generalize the gate self-exemption to all brain jobs

**Files:**
- Modify: `app/brain/gate.py` (add `BRAIN_JOB_PREFIX` + `BRAIN_ENRICH_JOB_NAME`; change `heavy_job_active`)
- Test: `tests/test_brain_gate_prefix.py`

**Interfaces:**
- Produces: `gate.BRAIN_JOB_PREFIX = "brain-"`, `gate.BRAIN_ENRICH_JOB_NAME = "brain-enrich"`; `heavy_job_active` excludes any job named `brain-%`.

**Why:** the enrich worker runs under `job_run("brain-enrich")` and then calls `gate.should_run`; if the gate still only excludes the literal `"brain-narrate"`, it counts enrich's own row as a heavy job and the worker self-blocks — the exact Phase 1 Critical. Generalizing to the `brain-` prefix fixes it for every present and future brain job. `brain-narrate` still matches `brain-%`, so the narrate task is unaffected.

- [ ] **Step 1: Write the failing test** `tests/test_brain_gate_prefix.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_brain_gate_prefix.py -v`
Expected: FAIL — `AttributeError: ... BRAIN_JOB_PREFIX` / brain-enrich row counted as heavy

- [ ] **Step 3: Edit `app/brain/gate.py`.** Replace the `BRAIN_JOB_NAME` constant block with:

```python
#: The brain's own job names share this prefix; they are excluded from the
#: heavy-job check so a brain task never backs off from a job_run row it just
#: opened on itself (the Phase 1 self-block, #410 — now generalized to every
#: brain job so brain-enrich doesn't reintroduce it).
BRAIN_JOB_PREFIX = "brain-"
BRAIN_JOB_NAME = "brain-narrate"
BRAIN_ENRICH_JOB_NAME = "brain-enrich"
```

Then in `heavy_job_active`, change the `JobRunRow.job != BRAIN_JOB_NAME` line to:

```python
            JobRunRow.job.not_like(f"{BRAIN_JOB_PREFIX}%"),
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_brain_gate_prefix.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Regression — the Phase 1 narrate gate + task still pass**

Run: `.venv/bin/pytest tests/test_brain_gate.py tests/test_brain_task.py -q`
Expected: PASS (unchanged — `brain-narrate` still excluded via the prefix)

- [ ] **Step 6: Format + lint + commit**

```bash
.venv/bin/ruff format app/brain/gate.py tests/test_brain_gate_prefix.py
.venv/bin/ruff check app/brain/gate.py tests/test_brain_gate_prefix.py
git add app/brain/gate.py tests/test_brain_gate_prefix.py
git commit -m "feat(brain): #413 generalize gate self-exemption to all brain- jobs"
```

---

### Task 2: story_gist table + migration + retention

**Files:**
- Modify: `app/db_models.py` (add `StoryGistRow`)
- Create: `migrations/versions/0015_story_gist.py`
- Modify: `app/housekeeping.py` (add `prune_story_gist` + wire into `run_retention_and_cap`)
- Test: `tests/test_story_gist_model.py`

**Interfaces:**
- Produces: `StoryGistRow(id, story_id, gist, category, escalating, model, method_version, created_at)`, unique `(story_id, method_version)`; `housekeeping.prune_story_gist(session, *, now=None) -> int`

- [ ] **Step 1: Write the failing test** `tests/test_story_gist_model.py`:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db_models import Base, StoryGistRow
from app.housekeeping import prune_story_gist


def test_story_gist_roundtrip():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            StoryGistRow(
                story_id=1,
                gist="Border clashes reported along a disputed frontier.",
                category="conflict",
                escalating="yes",
                model="qwen2.5:1.5b-instruct-q4_K_M",
                method_version="enrich-v1.0",
                created_at=datetime(2026, 7, 13, tzinfo=UTC),
            )
        )
        session.commit()
        row = session.execute(select(StoryGistRow)).scalar_one()
        assert row.category == "conflict"
        assert row.escalating == "yes"


def test_prune_story_gist_deletes_old():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 13, tzinfo=UTC)
    with Session(engine) as session:
        session.add_all(
            [
                StoryGistRow(
                    story_id=1, gist="old", category="other", escalating="unclear",
                    model="m", method_version="enrich-v1.0",
                    created_at=now - timedelta(days=31),
                ),
                StoryGistRow(
                    story_id=2, gist="new", category="other", escalating="unclear",
                    model="m", method_version="enrich-v1.0",
                    created_at=now - timedelta(days=1),
                ),
            ]
        )
        session.commit()
        deleted = prune_story_gist(session, now=now)
        session.commit()
        assert deleted == 1
        assert session.execute(select(StoryGistRow.gist)).scalars().all() == ["new"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_story_gist_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'StoryGistRow'`

- [ ] **Step 3: Add the model.** Append to `app/db_models.py`:

```python
class StoryGistRow(Base):
    """A light per-story gist + tags from the 1.5b brain (#413).

    One row per (story, method version), idempotent like story_claims; 30-day
    retention. Timely first-look that complements the nightly 4b claim layer.
    """

    __tablename__ = "story_gist"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gist: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    escalating: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    method_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("story_id", "method_version", name="story_gist_unique"),
        Index("story_gist_created_idx", "created_at"),
    )
```

> **Note:** `UniqueConstraint` and `Index` are already imported in `app/db_models.py` (used by sibling rows like `StoryReviewRow`). `BigInteger`, `Text`, `DateTime`, `func`, `Mapped`, `mapped_column`, `BigIntPK` are all in scope.

- [ ] **Step 4: Run to verify the model test passes**

Run: `.venv/bin/pytest tests/test_story_gist_model.py::test_story_gist_roundtrip -v`
Expected: PASS

- [ ] **Step 5: Create the migration** `migrations/versions/0015_story_gist.py`:

```python
"""Story gist + tags — the brain's light enrichment layer (#413).

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_gist",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("story_id", sa.BigInteger, nullable=False),
        sa.Column("gist", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("escalating", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("method_version", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("story_id", "method_version", name="story_gist_unique"),
    )
    op.create_index("story_gist_created_idx", "story_gist", ["created_at"])


def downgrade() -> None:
    op.drop_index("story_gist_created_idx", table_name="story_gist")
    op.drop_table("story_gist")
```

- [ ] **Step 6: Add the retention prune.** In `app/housekeeping.py`, add the helper (near `prune_brain_narrative`):

```python
def prune_story_gist(session: Session, *, now: datetime | None = None) -> int:
    """Delete story gists older than the news retention window (#413)."""
    from app.db_models import StoryGistRow

    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.retention_news_days)
    result = session.execute(delete(StoryGistRow).where(StoryGistRow.created_at < cutoff))
    return result.rowcount or 0
```

Then wire it into `run_retention_and_cap` next to the brain-narrative prune:

```python
    deleted_by_source["story_gist"] = prune_story_gist(session, now=now)
```

- [ ] **Step 7: Run the gist tests + housekeeping regression**

Run: `.venv/bin/pytest tests/test_story_gist_model.py -v && .venv/bin/pytest tests/ -k housekeeping -q`
Expected: PASS (both gist tests + housekeeping suite)

- [ ] **Step 8: Verify the migration applies**

Run: `.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head`
Expected: clean up/down/up (uses the configured dev Postgres from `make start`). If Postgres is unreachable, verify the file imports and reports `0015 0014`:
`.venv/bin/python -c "import importlib.util; s=importlib.util.spec_from_file_location('m','migrations/versions/0015_story_gist.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.revision, m.down_revision)"` → `0015 0014`.

- [ ] **Step 9: Format + lint + commit**

```bash
.venv/bin/ruff format app/db_models.py migrations/versions/0015_story_gist.py app/housekeeping.py tests/test_story_gist_model.py
.venv/bin/ruff check app/db_models.py migrations/versions/0015_story_gist.py app/housekeeping.py tests/test_story_gist_model.py
git add app/db_models.py migrations/versions/0015_story_gist.py app/housekeeping.py tests/test_story_gist_model.py
git commit -m "feat(brain): #413 story_gist table, migration 0015, 30-day retention"
```

---

### Task 3: Enrich prompt + parser (`app/brain/enrich.py`)

**Files:**
- Create: `app/brain/enrich.py` (constants + `build_gist_prompt` + `parse_gist` only; the worker is Task 4)
- Test: `tests/test_brain_enrich_parse.py`

**Interfaces:**
- Produces:
  - `CATEGORIES: frozenset[str]`, `ESCALATING: frozenset[str]`, `METHOD_VERSION: str = "enrich-v1.0"`, `GIST_MAX_CHARS: int`
  - `build_gist_prompt(titles: list[str]) -> str`
  - `parse_gist(raw: dict[str, Any]) -> dict[str, str]` → `{"gist", "category", "escalating"}`

- [ ] **Step 1: Write the failing test** `tests/test_brain_enrich_parse.py`:

```python
from app.brain import enrich


def test_parse_gist_keeps_valid_values():
    out = enrich.parse_gist(
        {"gist": "Border clashes reported.", "category": "conflict", "escalating": "yes"}
    )
    assert out == {
        "gist": "Border clashes reported.",
        "category": "conflict",
        "escalating": "yes",
    }


def test_parse_gist_coerces_off_enum_to_fallbacks():
    out = enrich.parse_gist(
        {"gist": "x", "category": "sports", "escalating": "maybe"}
    )
    assert out["category"] == "other"
    assert out["escalating"] == "unclear"


def test_parse_gist_handles_missing_keys():
    out = enrich.parse_gist({})
    assert out["gist"] == ""
    assert out["category"] == "other"
    assert out["escalating"] == "unclear"


def test_parse_gist_truncates_long_gist():
    out = enrich.parse_gist({"gist": "z" * 999, "category": "other", "escalating": "no"})
    assert len(out["gist"]) <= enrich.GIST_MAX_CHARS


def test_build_gist_prompt_has_enums_and_titles():
    prompt = enrich.build_gist_prompt(["Border clashes reported", "Troops mass at frontier"])
    assert "conflict" in prompt and "escalating" in prompt
    assert "only" in prompt.lower()  # no-fabrication
    assert "Border clashes reported" in prompt
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_brain_enrich_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.brain.enrich'`

- [ ] **Step 3: Implement `app/brain/enrich.py`**

```python
"""The brain's story enrichment (#413) — a light gist + two enum tags per story.

Timely first-look from the 1.5b model on idle windows; complements the nightly
4b claim extraction. No-fabrication: the gist describes only the supplied
headlines. The tags are fixed enums so a small model stays reliable and the
values are filterable — anything off-enum is coerced to a safe fallback.
"""

from __future__ import annotations

import json
from typing import Any

CATEGORIES: frozenset[str] = frozenset(
    {"conflict", "economy", "disaster", "politics", "other"}
)
ESCALATING: frozenset[str] = frozenset({"yes", "no", "unclear"})

METHOD_VERSION: str = "enrich-v1.0"
PROMPT_VERSION: str = "enrich-prompt-v1.0"
GIST_MAX_CHARS: int = 240

#: How many member headlines the prompt carries — enough signal, bounded tokens.
MAX_TITLES: int = 5


def build_gist_prompt(titles: list[str]) -> str:
    headlines = "\n".join(f"- {t}" for t in titles if t)
    return (
        "You summarize a news story for an OSINT dashboard. Below are the "
        "headlines of the outlets telling one story. Using ONLY these headlines "
        "(invent nothing), return a JSON object with exactly these keys:\n"
        '  "gist": one short plain-English sentence, what this story is.\n'
        '  "category": one of conflict, economy, disaster, politics, other.\n'
        '  "escalating": one of yes, no, unclear — is the situation intensifying?\n\n'
        f"HEADLINES:\n{headlines}"
    )


def parse_gist(raw: dict[str, Any]) -> dict[str, str]:
    gist = raw.get("gist")
    gist = gist.strip()[:GIST_MAX_CHARS] if isinstance(gist, str) else ""
    category = raw.get("category")
    category = category if category in CATEGORIES else "other"
    escalating = raw.get("escalating")
    escalating = escalating if escalating in ESCALATING else "unclear"
    return {"gist": gist, "category": category, "escalating": escalating}


def _pretty(payload: dict[str, str]) -> str:
    """Compact JSON — handy for `make enrich` output and debugging."""
    return json.dumps(payload, ensure_ascii=False)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_brain_enrich_parse.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Format + lint + commit**

```bash
.venv/bin/ruff format app/brain/enrich.py tests/test_brain_enrich_parse.py
.venv/bin/ruff check app/brain/enrich.py tests/test_brain_enrich_parse.py
git add app/brain/enrich.py tests/test_brain_enrich_parse.py
git commit -m "feat(brain): #413 gist prompt + enum-coercing parser"
```

---

### Task 4: Enrich worker + beat + routing + make target

**Files:**
- Modify: `app/brain/enrich.py` (add `_enrich_body`)
- Create: `app/brain/enrich_run.py`
- Modify: `app/tasks.py` (import + `brain_enrich` task + beat entry)
- Modify: `app/celery_app.py` (route `app.tasks.brain_enrich` to `analytics`)
- Modify: `Makefile` (`enrich` target + `.PHONY`)
- Test: `tests/test_brain_enrich_worker.py`

**Interfaces:**
- Consumes: `gate.should_run`, `gate.BRAIN_ENRICH_JOB_NAME`, `client.generate_json`, `StoryGistRow`, `StoryRow`, `StoryMemberRow`, `EventRow`, `WINDOW_HOURS`, `job_run`
- Produces: `enrich._enrich_body(*, now=None, batch_limit=None) -> dict[str, Any]`; Celery task `app.tasks.brain_enrich`

- [ ] **Step 1: Write the failing test** `tests/test_brain_enrich_worker.py`:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.brain import enrich
from app.db_models import Base, EventRow, StoryGistRow, StoryMemberRow, StoryRow


def _factory_with_story(now):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as s:
        story = StoryRow(
            title="Border clashes reported",
            first_seen=now - timedelta(hours=2),
            last_seen=now,
            member_count=1,
            outlet_count=1,
            owner_count=1,
            method_version="stories-v1.0",
        )
        s.add(story)
        s.flush()
        event = EventRow(
            source="gdelt",
            source_event_id="e1",
            occurred_at=now,
            fetched_at=now,
            category="conflict",
            payload={"title": "Border clashes reported along frontier"},
        )
        s.add(event)
        s.flush()
        s.add(StoryMemberRow(event_id=event.id, story_id=story.id, similarity=1.0))
        s.commit()
    return factory


def test_enrich_persists_one_gist_per_story(monkeypatch):
    now = datetime.now(UTC)
    factory = _factory_with_story(now)
    monkeypatch.setattr(enrich, "_session_factory", lambda: factory)
    monkeypatch.setattr(enrich.gate, "should_run", lambda session, now=None: (True, "ok"))
    monkeypatch.setattr(
        enrich.client,
        "generate_json",
        lambda prompt: {"gist": "Clashes.", "category": "conflict", "escalating": "yes"},
    )
    result = enrich._enrich_body(now=now)
    assert result["enriched"] == 1
    with factory() as s:
        row = s.execute(select(StoryGistRow)).scalar_one()
        assert row.category == "conflict"
    # idempotent: a second run enriches nothing new
    result2 = enrich._enrich_body(now=now)
    assert result2["enriched"] == 0
    assert result2["skipped_existing"] == 1


def test_enrich_skips_when_gated(monkeypatch):
    now = datetime.now(UTC)
    factory = _factory_with_story(now)
    monkeypatch.setattr(enrich, "_session_factory", lambda: factory)
    monkeypatch.setattr(enrich.gate, "should_run", lambda session, now=None: (False, "low RAM"))
    result = enrich._enrich_body(now=now)
    assert result["enriched"] == 0
    assert result.get("reason") == "low RAM"
    with factory() as s:
        assert s.execute(select(StoryGistRow)).first() is None


def test_enrich_failed_story_does_not_abort_batch(monkeypatch):
    now = datetime.now(UTC)
    factory = _factory_with_story(now)
    monkeypatch.setattr(enrich, "_session_factory", lambda: factory)
    monkeypatch.setattr(enrich.gate, "should_run", lambda session, now=None: (True, "ok"))

    def _boom(prompt):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(enrich.client, "generate_json", _boom)
    result = enrich._enrich_body(now=now)
    assert result["failed"] == 1
    assert result["enriched"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_brain_enrich_worker.py -v`
Expected: FAIL — `AttributeError: module 'app.brain.enrich' has no attribute '_enrich_body'`

- [ ] **Step 3: Add the worker to `app/brain/enrich.py`.** Add these imports at the top (with the existing ones):

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from app.brain import client, gate
from app.db import get_engine
from app.db_models import EventRow, StoryGistRow, StoryMemberRow, StoryRow
from app.settings import settings
from app.stories.task import WINDOW_HOURS

DEFAULT_BATCH_LIMIT: int = 20
```

Then append the worker:

```python
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def _titles_for(session: Session, story_id: int) -> list[str]:
    payloads = (
        session.execute(
            select(EventRow.payload)
            .join(StoryMemberRow, StoryMemberRow.event_id == EventRow.id)
            .where(StoryMemberRow.story_id == story_id)
            .limit(MAX_TITLES)
        )
        .scalars()
        .all()
    )
    return [(p or {}).get("title") or "" for p in payloads]


def _insert_gist_if_absent(session: Session, *, story_id: int, parsed: dict[str, str]) -> bool:
    values = {
        "story_id": story_id,
        "gist": parsed["gist"],
        "category": parsed["category"],
        "escalating": parsed["escalating"],
        "model": settings.brain_model,
        "method_version": METHOD_VERSION,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        base = pg_insert(StoryGistRow).values(values)
    elif dialect == "sqlite":
        base = sqlite_insert(StoryGistRow).values(values)
    else:
        raise NotImplementedError(f"_insert_gist_if_absent: unsupported dialect {dialect!r}")
    stmt = base.on_conflict_do_nothing(
        index_elements=["story_id", "method_version"]
    ).returning(StoryGistRow.id)
    inserted = session.execute(stmt).scalar_one_or_none()
    session.commit()
    return inserted is not None


def _enrich_body(*, now: datetime | None = None, batch_limit: int | None = None) -> dict[str, Any]:
    from app.jobs.heartbeat import job_run

    now = now or datetime.now(UTC)
    limit = batch_limit if batch_limit is not None else DEFAULT_BATCH_LIMIT
    factory = _session_factory()
    counters: dict[str, Any] = {"window_stories": 0, "enriched": 0, "skipped_existing": 0, "failed": 0}

    with job_run(gate.BRAIN_ENRICH_JOB_NAME, session_factory=factory, evict_brain=False):
        with factory() as session:
            allowed, reason = gate.should_run(session, now=now)
            if not allowed:
                counters["reason"] = reason
                return counters

            cutoff = now - timedelta(hours=WINDOW_HOURS)
            stories = (
                session.execute(
                    select(StoryRow.id)
                    .where(StoryRow.last_seen >= cutoff)
                    .order_by(StoryRow.last_seen.desc())
                )
                .scalars()
                .all()
            )
            counters["window_stories"] = len(stories)

            for story_id in stories:
                if counters["enriched"] >= limit:
                    break
                existing = session.execute(
                    select(StoryGistRow.id).where(
                        StoryGistRow.story_id == story_id,
                        StoryGistRow.method_version == METHOD_VERSION,
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    counters["skipped_existing"] += 1
                    continue
                titles = [t for t in _titles_for(session, story_id) if t]
                if not titles:
                    continue
                try:
                    raw = client.generate_json(build_gist_prompt(titles))
                except Exception:
                    counters["failed"] += 1
                    continue
                if _insert_gist_if_absent(session, story_id=story_id, parsed=parse_gist(raw)):
                    counters["enriched"] += 1
                else:
                    counters["skipped_existing"] += 1

    return counters
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_brain_enrich_worker.py -v`
Expected: PASS (3 tests)

> **Note (verified in `app/db_models.py`):** `EventRow` non-null columns are `source, source_event_id, occurred_at, fetched_at, category, keywords (default list), payload` — the seed sets all required ones (`keywords` uses its Python-side default). The worker itself only reads `EventRow.payload`.

- [ ] **Step 5: Create `app/brain/enrich_run.py`**

```python
"""Run one enrichment pass — `make enrich` / `python -m app.brain.enrich_run`."""

from __future__ import annotations

from app.brain.enrich import _enrich_body


def main() -> None:
    print(_enrich_body())


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Register the Celery task.** In `app/tasks.py`, add the import near the other brain import (`from app.brain.task import _narrate_body`):

```python
from app.brain.enrich import _enrich_body
```

Then add the task (after `brain_narrate`):

```python
@app.task(
    name="app.tasks.brain_enrich",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def brain_enrich() -> dict[str, Any]:
    """The brain (#413): gist + tag window stories that lack one, on idle windows."""
    return _enrich_body()
```

And the beat entry inside `app.conf.beat_schedule`:

```python
    # The brain enriches new stories every 20 min when the box is idle (#413).
    "brain-enrich-20min": {
        "task": "app.tasks.brain_enrich",
        "schedule": crontab(minute="*/20"),
    },
```

- [ ] **Step 7: Route to analytics.** In `app/celery_app.py`, add to the `task_routes` tuple (after `"app.tasks.brain_narrate",`):

```python
        "app.tasks.brain_enrich",
```

- [ ] **Step 8: Makefile target.** In `Makefile`, after the `brain` target add and append `enrich` to `.PHONY`:

```makefile
enrich:  ## Run one brain enrichment pass — gist + tags for new stories (#413)
	.venv/bin/python -m app.brain.enrich_run
```

- [ ] **Step 9: Verify wiring imports cleanly**

Run: `.venv/bin/python -c "import app.tasks, app.celery_app; print('brain-enrich-20min' in app.tasks.app.conf.beat_schedule); print(app.celery_app.app.conf.task_routes['app.tasks.brain_enrich'])"`
Expected: `True` then `{'queue': 'analytics'}`

- [ ] **Step 10: Format + lint + commit**

```bash
.venv/bin/ruff format app/brain/enrich.py app/brain/enrich_run.py app/tasks.py app/celery_app.py tests/test_brain_enrich_worker.py
.venv/bin/ruff check app/brain/ app/tasks.py app/celery_app.py tests/test_brain_enrich_worker.py
git add app/brain/enrich.py app/brain/enrich_run.py app/tasks.py app/celery_app.py Makefile tests/test_brain_enrich_worker.py
git commit -m "feat(brain): #413 enrich worker — beat every 20m, analytics queue, make enrich"
```

---

### Task 5: `/stories/top` carries gist + tags

**Files:**
- Modify: `app/api.py` (`stories_top`: add gist fields; import `StoryGistRow` + `enrich.METHOD_VERSION`)
- Test: `tests/test_stories_gist_api.py`

**Interfaces:**
- Produces: each `/stories/top` item gains `gist: str | None`, `category: str | None`, `escalating: str | None`.

- [ ] **Step 1: Write the failing test** `tests/test_stories_gist_api.py`:

```python
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import app, get_session
from app.brain import enrich
from app.db_models import Base, StoryGistRow, StoryRow


def _client_and_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)

    def override():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    return TestClient(app), factory


def test_stories_top_includes_gist_when_present():
    client, factory = _client_and_factory()
    now = datetime.now(UTC)
    with factory() as s:
        story = StoryRow(
            title="Border clashes", first_seen=now - timedelta(hours=1), last_seen=now,
            member_count=2, outlet_count=2, owner_count=1, method_version="stories-v1.0",
        )
        s.add(story)
        s.flush()
        s.add(
            StoryGistRow(
                story_id=story.id, gist="Clashes at the frontier.", category="conflict",
                escalating="yes", model="m", method_version=enrich.METHOD_VERSION,
                created_at=now,
            )
        )
        s.commit()
    body = client.get("/stories/top").json()
    assert body[0]["gist"] == "Clashes at the frontier."
    assert body[0]["category"] == "conflict"
    assert body[0]["escalating"] == "yes"
    app.dependency_overrides.clear()


def test_stories_top_gist_null_when_absent():
    client, factory = _client_and_factory()
    now = datetime.now(UTC)
    with factory() as s:
        s.add(
            StoryRow(
                title="Quiet story", first_seen=now - timedelta(hours=1), last_seen=now,
                member_count=1, outlet_count=1, owner_count=1, method_version="stories-v1.0",
            )
        )
        s.commit()
    body = client.get("/stories/top").json()
    assert body[0]["gist"] is None
    assert body[0]["category"] is None
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_stories_gist_api.py -v`
Expected: FAIL — `KeyError: 'gist'`

- [ ] **Step 3: Add gist to `stories_top`.** In `app/api.py`, add `StoryGistRow` to the `app.db_models` import block and `from app.brain import enrich` (or reuse the existing `from app.brain import ...` line — add `enrich`). Then in `stories_top`, after the `checks` dict is built, add a gist lookup and include the fields in the returned dict:

```python
    gists: dict[int, StoryGistRow] = {}
    if story_ids:
        for g in session.execute(
            select(StoryGistRow).where(
                StoryGistRow.story_id.in_(story_ids),
                StoryGistRow.method_version == enrich.METHOD_VERSION,
            )
        ).scalars():
            gists[g.story_id] = g
```

And in the per-story dict comprehension add:

```python
            "gist": gists[story.id].gist if story.id in gists else None,
            "category": gists[story.id].category if story.id in gists else None,
            "escalating": gists[story.id].escalating if story.id in gists else None,
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_stories_gist_api.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Format + lint + commit**

```bash
.venv/bin/ruff format app/api.py tests/test_stories_gist_api.py
.venv/bin/ruff check app/api.py tests/test_stories_gist_api.py
git add app/api.py tests/test_stories_gist_api.py
git commit -m "feat(brain): #413 /stories/top carries gist + tags"
```

---

### Task 6: Stories card shows gist + tag chip

**Files:**
- Modify: `osint-frontend/lib/analytics.ts` (`StoryRow` interface gains `gist/category/escalating`)
- Modify: `osint-frontend/components/panels/StoriesPanel.tsx` (render gist line + tag chip under the title)
- Test: `osint-frontend/lib/storyGist.test.mts`

**Interfaces:**
- Consumes: the `/stories/top` gist fields.

- [ ] **Step 1: Write the failing test** `osint-frontend/lib/storyGist.test.mts`:

```typescript
import { describe, expect, it, vi, afterEach } from "vitest"
import { fetchTopStories } from "./analytics"

afterEach(() => vi.restoreAllMocks())

describe("fetchTopStories carries gist fields", () => {
  it("parses gist/category/escalating", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => [
          {
            id: "1", title: "Border clashes", first_seen: "x", last_seen: "y",
            member_count: 2, outlet_count: 2, owner_count: 1, corroboration: null,
            corroboration_components: null, sensor_checks: {}, method_version: "stories-v1.0",
            gist: "Clashes at the frontier.", category: "conflict", escalating: "yes",
          },
        ],
      })),
    )
    const rows = await fetchTopStories(24, 10)
    expect(rows[0].gist).toBe("Clashes at the frontier.")
    expect(rows[0].category).toBe("conflict")
  })
})
```

- [ ] **Step 2: Register the test + run to fail.** Add `"lib/storyGist.test.mts"` to `osint-frontend/vitest.config.ts` `test.include`, then:

Run: `cd osint-frontend && pnpm test storyGist`
Expected: FAIL — `gist` is not on the `StoryRow` type (tsc/type error in the test) or the property is undefined.

- [ ] **Step 3: Extend the `StoryRow` interface** in `osint-frontend/lib/analytics.ts`:

```typescript
export interface StoryRow {
  id: string
  title: string
  first_seen: string
  last_seen: string
  member_count: number
  outlet_count: number
  owner_count: number
  corroboration: number | null
  corroboration_components: Record<string, unknown> | null
  sensor_checks: Record<string, string>
  method_version: string
  gist: string | null
  category: string | null
  escalating: string | null
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd osint-frontend && pnpm test storyGist`
Expected: PASS

- [ ] **Step 5: Render the gist + chip.** In `osint-frontend/components/panels/StoriesPanel.tsx`, find the story title span (`<span ... title={story.title}>{story.title}</span>`, around line 110). Immediately after the element that contains the title, render the gist line + tag chip when present. Add this block right after the title-row element:

```tsx
      {story.gist ? (
        <p className="px-4 pb-1 text-[11px] leading-snug text-neutral-400">
          {story.gist}
          {story.category ? (
            <span className="ml-2 rounded border border-neutral-700 px-1 py-0.5 font-mono text-[9px] uppercase tracking-wide text-neutral-400">
              {story.category}
              {story.escalating === "yes" ? " ↑" : ""}
            </span>
          ) : null}
        </p>
      ) : null}
```

> **Note for the implementer:** read `StoriesPanel.tsx` first and place this block inside the same story-card container as the title, immediately below the title row (not inside the `<span>`). Match the surrounding JSX structure; if the title sits in a flex row, put the gist `<p>` as the next sibling block below that row. Keep the existing corroboration/sensor UI untouched.

- [ ] **Step 6: Typecheck + test**

Run: `cd osint-frontend && pnpm test storyGist && pnpm exec tsc --noEmit`
Expected: PASS + no type errors

- [ ] **Step 7: Commit**

```bash
git add osint-frontend/lib/analytics.ts osint-frontend/lib/storyGist.test.mts osint-frontend/vitest.config.ts osint-frontend/components/panels/StoriesPanel.tsx
git commit -m "feat(brain): #413 Stories card shows gist + tag chip"
```

---

### Task 7: README §4.6

**Files:**
- Modify: `README.md` (add §4.6 under Chapter 4, before `# Chapter 5`)

- [ ] **Step 1: Insert the subsection** immediately before `# Chapter 5 — How to read the dashboard` (after §4.5):

```markdown
### 4.6 Enriching new stories

The nightly validator gives stories full claims once a night with the heavy 4b model.
The brain adds a faster, lighter first-look: every ~20 minutes, on idle windows, the
1.5b model gives each new story a one-line **gist** plus two tags — a **category**
(`conflict`, `economy`, `disaster`, `politics`, `other`) and an **escalating** flag
(`yes`, `no`, `unclear`). It reads only the story's own headlines and invents nothing;
anything a small model returns off-vocabulary is coerced to `other` / `unclear`, so the
tags stay clean and filterable.

The pass is idle-gated (same RAM + no-heavy-job gate as the narrative) and batch-capped
(~20 stories per run), so a burst of new stories clears within an hour or two without
straining the Pi. Gists land on `/stories/top` and show as a line under each story on
the Stories card, with a small category chip (↑ marks an escalating story). Run one pass
by hand with `make enrich`. Stored 30 days, then pruned.
```

- [ ] **Step 2: Verify placement**

Run: `grep -n "### 4.6 Enriching\|### 4.5 Ask\|# Chapter 5 — How to read" README.md`
Expected: `### 4.6` appears after `### 4.5` and before `# Chapter 5`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(brain): #413 README §4.6 — enriching new stories"
```

---

### Task 8: Verify end-to-end + PR + issue log

**Files:** none (integration + reporting)

- [ ] **Step 1: Full backend sweep**

Run: `.venv/bin/pytest tests/ -q`
Expected: all pass (new gate/gist/enrich/api tests + no regressions)

- [ ] **Step 2: Lint gates (CI parity)**

Run: `.venv/bin/ruff check app/ tests/ && .venv/bin/ruff format --check app/ tests/`
Expected: clean

- [ ] **Step 3: Frontend gates**

Run: `cd osint-frontend && pnpm test && pnpm exec tsc --noEmit`
Expected: all vitest pass + no type errors

- [ ] **Step 4: Live smoke (Ollama running, model pulled).** From repo root — build a story in SQLite and enrich it through the real model:

```bash
.venv/bin/python -c "
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.brain import enrich, client
titles = ['Border clashes reported along disputed frontier', 'Troops mass near the border overnight']
raw = client.generate_json(enrich.build_gist_prompt(titles))
print('PARSED:', enrich.parse_gist(raw))
client.evict()
"
```
Expected: prints a parsed dict with a coherent gist, `category` in the enum, `escalating` in the enum. Confirms the real model round-trips the enrichment prompt and the parser accepts it.

- [ ] **Step 5: Push + PR** (links #413):

```bash
git push -u origin feat/brain-enrichment
gh pr create --title "feat(brain): story enrichment — gist + tags per new story (Phase 3)" \
  --body "Closes #413. Phase 3 of the brain: an idle-gated brain_enrich pass gives each new story a one-line gist + two enum tags (category, escalating) from the 1.5b model, surfaced on the Stories card. Idempotent per story, 30-day retention. Generalizes the Phase 1 gate self-exemption to all brain- jobs so enrich doesn't self-block. Design: docs/superpowers/specs/2026-07-13-brain-enrichment-design.md."
```

- [ ] **Step 6: Post the close-out comment on #413** — what shipped, the enum vocabulary, `make enrich`, and that per-event enrichment / gist-fed-context / filtering-UI remain deferred. Basil merges.

---

## Self-Review

**Spec coverage:**
- §4.1 generalize gate exemption → Task 1. ✓
- §4.2 enrich.py prompt/parse → Task 3. ✓
- §4.3 worker (gate, idempotent, one bad story continues) → Task 4. ✓
- §4.4 story_gist table + migration 0015 + retention → Task 2. ✓
- §4.5 beat + routing + make → Task 4. ✓
- §5 /stories/top gist + card → Task 5 + Task 6. ✓
- §6 error handling → Task 3 (coercion) + Task 4 (gated skip, failed continues). ✓
- §7 testing → each task TDD. ✓
- §8 README §4.6 → Task 7. ✓
- §9 deliverables → covered; PR + #413 log in Task 8. ✓

**Placeholder scan:** No TBD/TODO; the two "Note" callouts point at verified column facts and a concrete placement instruction, not deferred work.

**Type consistency:** `_enrich_body(*, now, batch_limit)`, `build_gist_prompt(titles)`, `parse_gist(raw)`, `METHOD_VERSION`, `gate.BRAIN_ENRICH_JOB_NAME` consistent across enrich.py, tasks.py, api.py, and tests. `StoryGistRow(story_id, gist, category, escalating, model, method_version, created_at)` identical in model, migration, worker insert, api, retention, and tests. Gate `heavy_job_active` prefix exemption consistent with the narrate task's `job_run(gate.BRAIN_JOB_NAME)` (still `brain-narrate`, still matched by `brain-%`). Frontend `StoryRow.gist/category/escalating` consistent across the type, the test, and the card.
