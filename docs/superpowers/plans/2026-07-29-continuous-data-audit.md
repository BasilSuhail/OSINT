# Continuous Data Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the existing #580 source-data audit on a nightly clock with persistent history, so "50 findings across 47 sources" becomes a trend instead of a weeks-old snapshot.

**Architecture:** A new `app/audit/task.py` orchestrates the already-pure `app.audit.run.audit()` — it persists one `audit_runs` row plus one `audit_findings` row per finding, diffs `(source, check)` against the last *completed* run, and pushes only findings that are new. Rules in `app/audit/checks.py` are untouched. Runs nightly through `job_run()` because it costs two full scans over 1.29M rows.

**Tech Stack:** Python 3.14, SQLAlchemy 2.x (Mapped/mapped_column), Alembic, Celery beat, pytest, sqlite in-memory for tests.

## Global Constraints

- **Issue:** #669. **Branch:** `669-audit-on-a-clock` (already created, spec already committed).
- **Worktree:** `/private/tmp/claude-501/-Users-basilsuhail-folders-OSINT/de0f87f7-7f7e-4ba0-ae61-88152ec0506e/scratchpad/wt-669` — run every command there, never in `/Users/basilsuhail/folders/OSINT` (Basil's jobs are live against that checkout).
- **Spec:** `docs/superpowers/specs/2026-07-29-continuous-data-audit-design.md`.
- **Detect only.** No quarantine, no auto-correction, no auto-disable, no dashboard work. If a step tempts you toward "and then fix the data", stop — that is a separate issue on purpose.
- **1 issue → 1 branch → 1 PR → 1 commit.** Commit after each task while working; the branch is squashed into one commit at PR time. Never merge — Basil merges.
- **No Claude attribution** in commit messages or PR body. No `Co-Authored-By: Claude`, no "Generated with".
- **Verify gates before pushing:** `.venv/bin/ruff check .` AND `.venv/bin/ruff format --check .` AND `.venv/bin/pytest`. Backend CI runs the format check too — `ruff check` alone passing is not enough.
- **Tests are hermetic sqlite** via the `db_session` fixture in `tests/conftest.py`. No docker required for the unit suite.
- Python: `from __future__ import annotations` at the top of every new module.

## Three deliberate deviations from the spec

All small, all flagged for Basil in the PR body:

1. **Column is `check_name`, not `check`.** `CHECK` is a reserved word in Postgres. SQLAlchemy would quote it, but the whole point of this table is that Basil can type ad-hoc trend queries against it — `SELECT check_name ...` beats `SELECT "check" ...`. The `Finding` dataclass attribute stays `check`; only the column differs.
2. **Crash signal is a missing row, not a NULL `finished_at`.** The spec described both. Doing both means two transactions for no gain: `job_run()` already records the failure in `job_runs`, and the #663 output watchdog watches `MAX(finished_at)`, which stops advancing either way. So the run row is written once, at the end, in a single transaction with its findings — a crashed audit writes nothing and pages via #663. The column stays nullable for the schema-level guarantee.

3. **Two entry points with different semantics, stated plainly.** The spec said a hand-run must not shift the delta baseline. That holds for `python scripts/data_audit.py`, which stays read-only and writes nothing — look without touching. But `make data-audit` runs *the job*, so it does write a run row, and tomorrow's delta will diff against it rather than against last night. That is honest rather than a defect: the diff has always meant "new since the last completed run", and a noon run captures true state at noon. The rule to keep straight is one line, and it belongs in the PR body: **the script reports, the make target runs.**

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `app/db_models.py` | Add `AuditRunRow`, `AuditFindingRow` | 1 |
| `migrations/versions/0022_audit_history.py` | Create both tables | 1 |
| `app/audit/run.py` | Add `audit_detail()` returning findings + source count; `audit()` delegates | 2 |
| `app/audit/task.py` | **New.** Persist, diff, notify, orchestrate | 2, 3 |
| `app/tasks.py` | Celery task + beat entry | 4 |
| `app/watchdog.py` | Register `data-audit` in `JOB_CADENCE_MIN` + `JOB_OUTPUT` | 4 |
| `Makefile` | `make data-audit` target | 4 |
| `tests/test_audit_history.py` | **New.** 9 tests | 2, 3 |
| `tests/test_watchdog_output.py` | One added registration test | 4 |

---

### Task 1: Tables and migration

**Files:**
- Modify: `app/db_models.py` (append after `SourceQuarantineRow`, around line 641)
- Create: `migrations/versions/0022_audit_history.py`
- Test: `tests/test_audit_history.py` (created here, one test)

**Interfaces:**
- Consumes: `Base`, `BigIntPK` from `app/db_models.py`
- Produces: `AuditRunRow(id, started_at, finished_at, sources_measured, findings_total)`, `AuditFindingRow(id, run_id, source, check_name, detail)`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_history.py`:

```python
"""Nightly source-data audit history (#669).

#580 built the only check that asks what the data *means*. It ran once. This
covers the machinery that gives it a clock and a memory — and, as hard as
anything else, the cases where it must stay silent. A guardrail that pages on
the 50 standing findings every morning is a guardrail nobody reads by Friday.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import AuditFindingRow, AuditRunRow

NOW = datetime(2026, 7, 29, 3, 40, tzinfo=UTC)


def test_findings_cascade_when_their_run_is_deleted(db_session: Session) -> None:
    run = AuditRunRow(
        started_at=NOW, finished_at=NOW, sources_measured=1, findings_total=1
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        AuditFindingRow(
            run_id=run.id,
            source="opensky-adsb",
            check_name="severity_constant",
            detail="severity is the same value on all 58,793 rows that carry one",
        )
    )
    db_session.flush()

    db_session.delete(run)
    db_session.flush()

    assert db_session.execute(select(AuditFindingRow)).scalars().all() == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /private/tmp/claude-501/-Users-basilsuhail-folders-OSINT/de0f87f7-7f7e-4ba0-ae61-88152ec0506e/scratchpad/wt-669
.venv/bin/pytest tests/test_audit_history.py -v
```

Expected: FAIL — `ImportError: cannot import name 'AuditRunRow' from 'app.db_models'`

- [ ] **Step 3: Add the models**

Append to `app/db_models.py`, after `SourceQuarantineRow`:

```python
class AuditRunRow(Base):
    """One sweep of the source-data audit (#580 machinery, now on a clock — #669).

    The row exists even when the audit finds nothing. An empty run is the
    healthy state and still has to be visible, or "clean" and "never ran" look
    identical — which is exactly the #663 failure shape one level up.

    Written once, at the end, in the same transaction as its findings. A run
    that crashes therefore leaves no row at all: `job_runs` records the failure
    and the output watchdog sees MAX(finished_at) stop advancing.
    """

    __tablename__ = "audit_runs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sources_measured: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    findings_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("audit_runs_started_idx", "started_at"),)


class AuditFindingRow(Base):
    """One finding inside one run. Mirrors `app.audit.checks.Finding`.

    `check_name` rather than `check`: CHECK is reserved in Postgres, and this
    table exists to be queried by hand.

    The delta that decides whether to notify compares (source, check_name) and
    deliberately ignores `detail` — the detail carries live row counts, so
    including it would page every night as those counts move.
    """

    __tablename__ = "audit_findings"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("audit_runs.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    check_name: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("audit_findings_run_idx", "run_id", "source"),)
```

Add `ForeignKey` to the `sqlalchemy` import block at the top of the file (it is not currently imported — check before adding, and keep the list alphabetical: it goes after `Float`).

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_audit_history.py -v
```

Expected: PASS.

If the cascade assertion fails on sqlite, add `passive_deletes=True` is **not** the fix here — there is no relationship configured, so SQLAlchemy issues the DELETE itself only if a relationship exists. Instead make the test explicit about what it checks by deleting through raw SQL is also wrong. The correct fix: sqlite does not enforce foreign keys unless `PRAGMA foreign_keys=ON`. If it fails, change the test to assert the FK constraint exists on the mapper instead:

```python
    fk = next(iter(AuditFindingRow.__table__.c.run_id.foreign_keys))
    assert fk.column.table.name == "audit_runs"
    assert fk.ondelete == "CASCADE"
```

Use whichever version passes; the point is that the cascade is declared.

- [ ] **Step 5: Write the migration**

Create `migrations/versions/0022_audit_history.py`:

```python
"""Persist the source-data audit's findings over time (#669).

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-29

#580 built the only check that asks whether the data means what it claims —
eight rules over 47 declared source expectations. It ran once, found 50
findings, and nothing since knows whether that is still the number.

One run row plus one row per finding, nightly. No retention: raw events expire
at 30 days, derived analytical tables do not, and pruning this would recreate
#586 — the retention window eating the history the trend needs. ~50 findings a
day is ~18k rows a year.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sources_measured", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("findings_total", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("audit_runs_started_idx", "audit_runs", ["started_at"])

    op.create_table(
        "audit_findings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("check_name", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["audit_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("audit_findings_run_idx", "audit_findings", ["run_id", "source"])


def downgrade() -> None:
    op.drop_index("audit_findings_run_idx", table_name="audit_findings")
    op.drop_table("audit_findings")
    op.drop_index("audit_runs_started_idx", table_name="audit_runs")
    op.drop_table("audit_runs")
```

- [ ] **Step 6: Verify the migration applies against the dev database**

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head
```

Expected: all three succeed, no errors. Round-tripping proves `downgrade()` is real rather than decorative.

- [ ] **Step 7: Commit**

```bash
git add app/db_models.py migrations/versions/0022_audit_history.py tests/test_audit_history.py
git commit -m "feat(audit): #669 tables for audit run history"
```

---

### Task 2: The pure layer — source count, delta, message

**Files:**
- Modify: `app/audit/run.py` (extract `audit_detail`, keep `audit` as a delegate)
- Create: `app/audit/task.py`
- Test: `tests/test_audit_history.py` (append)

**Interfaces:**
- Consumes: `app.audit.checks.Finding(source, check, detail)`, `app.audit.run.gather_stats`, `app.audit.expectations.for_source`
- Produces:
  - `app.audit.run.audit_detail(session, *, now=None) -> tuple[list[Finding], int]`
  - `app.audit.task.finding_keys(findings: Iterable[Finding]) -> set[tuple[str, str]]`
  - `app.audit.task.new_findings(previous: set[tuple[str, str]], current: Sequence[Finding]) -> list[Finding]`
  - `app.audit.task.format_message(new: Sequence[Finding], *, baseline: bool, findings_total: int, sources_measured: int) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_audit_history.py`:

```python
from app.audit.checks import Finding
from app.audit.task import MAX_NAMED, PUSHOVER_MAX_CHARS, finding_keys, format_message, new_findings


def _finding(source: str, check: str, detail: str = "detail") -> Finding:
    return Finding(source, check, detail)


def test_new_findings_returns_only_unseen_pairs() -> None:
    previous = {("opensky-adsb", "severity_constant"), ("gdacs", "severity_shape")}
    current = [
        _finding("opensky-adsb", "severity_constant"),
        _finding("gdacs", "severity_shape"),
        _finding("nasa-firms", "severity_constant"),
    ]

    assert new_findings(previous, current) == [_finding("nasa-firms", "severity_constant")]


def test_detail_change_alone_is_not_new() -> None:
    previous = finding_keys([_finding("opensky-adsb", "severity_constant", "58,793 rows")])
    current = [_finding("opensky-adsb", "severity_constant", "61,204 rows")]

    assert new_findings(previous, current) == []


def test_baseline_message_names_the_totals_not_the_findings() -> None:
    message = format_message(
        [_finding("a", "b")], baseline=True, findings_total=50, sources_measured=47
    )

    assert message == "data audit baseline: 50 findings across 47 sources"


def test_message_names_each_new_finding() -> None:
    message = format_message(
        [_finding("nasa-firms", "severity_constant"), _finding("rss-x", "country_coverage")],
        baseline=False,
        findings_total=52,
        sources_measured=47,
    )

    assert message == (
        "2 new audit findings: nasa-firms severity_constant · rss-x country_coverage"
    )


def test_message_truncates_past_five_and_stays_under_the_push_limit() -> None:
    many = [_finding(f"source-{i:02d}", "severity_constant") for i in range(50)]

    message = format_message(many, baseline=False, findings_total=90, sources_measured=47)

    assert message.startswith("50 new audit findings: ")
    assert message.count("·") == MAX_NAMED - 1
    assert message.endswith(f"… +{50 - MAX_NAMED} more")
    assert len(message) < PUSHOVER_MAX_CHARS
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_audit_history.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.audit.task'`

- [ ] **Step 3: Extract `audit_detail` in `app/audit/run.py`**

Replace the existing `audit()` function (currently the last function in the file) with:

```python
def audit_detail(session: Session, *, now: datetime | None = None) -> tuple[list[Finding], int]:
    """Findings, plus how many sources were measured to produce them.

    The count cannot be derived from the findings: a source with nothing wrong
    contributes zero findings and still has to count as measured, or a clean
    night looks like a night the audit never ran.
    """
    moment = now or datetime.now(UTC)
    stats = gather_stats(session)
    findings: list[checks.Finding] = []
    for source_stats in stats:
        expectation = expectations.for_source(source_stats.source)
        if expectation is None:
            findings.append(
                checks.Finding(
                    source_stats.source,
                    "undeclared_source",
                    f"{source_stats.rows:,} rows, but no expectation declares what this "
                    f"source should produce",
                )
            )
            continue
        findings.extend(checks.run_all(source_stats, expectation, now=moment))
    return findings, len(stats)


def audit(session: Session, *, now: datetime | None = None) -> list[checks.Finding]:
    """Every finding across every source, plus any source nothing declares."""
    return audit_detail(session, now=now)[0]
```

Note the annotation on `audit_detail` uses `Finding` — add `from app.audit.checks import Finding` to the imports, or write the annotation as `tuple[list[checks.Finding], int]` to avoid a second import. Prefer the latter; it matches how the rest of the file refers to `checks.Finding`.

- [ ] **Step 4: Verify the existing audit tests still pass**

```bash
.venv/bin/pytest tests/test_audit_run.py tests/test_audit_checks.py -v
```

Expected: PASS, unchanged. `audit()` keeps its exact signature and behaviour — this is why the refactor is safe.

- [ ] **Step 5: Create `app/audit/task.py` with the pure layer**

```python
"""Nightly source-data audit: record, diff, notify (#669).

`app.audit.run` measures. This records what it measured and says something only
when the answer changed. The rules themselves are untouched.

The split matters: there are ~50 standing findings. A check that pushes all of
them every night is noise by the second morning, and a muted channel is worse
than no channel — it is a channel everyone believes is working.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.audit.checks import Finding

#: How many new findings a push names before it summarises the rest. Pushover
#: truncates around 1024 characters and 50 new findings would blow past it; the
#: full list is in `audit_findings` either way.
MAX_NAMED = 5

#: Pushover's message ceiling. Asserted against in tests rather than trusted.
PUSHOVER_MAX_CHARS = 1024


def finding_keys(findings: Iterable[Finding]) -> set[tuple[str, str]]:
    """The identity of a finding for diffing: which rule objects to which source.

    `detail` is deliberately excluded. It carries live row counts, so including
    it would make every finding "new" every night as those counts move.
    """
    return {(f.source, f.check) for f in findings}


def new_findings(previous: set[tuple[str, str]], current: Sequence[Finding]) -> list[Finding]:
    """Findings present now and absent from the previous completed run."""
    return [f for f in current if (f.source, f.check) not in previous]


def format_message(
    new: Sequence[Finding],
    *,
    baseline: bool,
    findings_total: int,
    sources_measured: int,
) -> str:
    """The push text. Baseline states the position; every later run states the change."""
    if baseline:
        return (
            f"data audit baseline: {findings_total} findings "
            f"across {sources_measured} sources"
        )
    named = " · ".join(f"{f.source} {f.check}" for f in new[:MAX_NAMED])
    message = f"{len(new)} new audit findings: {named}"
    if len(new) > MAX_NAMED:
        message = f"{message} … +{len(new) - MAX_NAMED} more"
    return message
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_audit_history.py -v
```

Expected: PASS, all 5 tests so far.

- [ ] **Step 7: Commit**

```bash
git add app/audit/run.py app/audit/task.py tests/test_audit_history.py
git commit -m "feat(audit): #669 delta and message shape for audit runs"
```

---

### Task 3: Persistence and the notify body

**Files:**
- Modify: `app/audit/task.py`
- Test: `tests/test_audit_history.py` (append)

**Interfaces:**
- Consumes: `AuditRunRow`, `AuditFindingRow`, `NotificationRow`, `app.watchdog._persist_notification`, `app.watchdog._pushover_send`, `audit_detail`, `finding_keys`, `new_findings`, `format_message`
- Produces: `app.audit.task.run_audit(session, *, now=None) -> dict[str, int]` returning `{"sources": int, "findings": int, "new": int, "pushed": int}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_audit_history.py`:

```python
from unittest.mock import patch

from app.db_models import NotificationRow


def _completed_run(
    session: Session,
    *,
    when: datetime,
    findings: list[tuple[str, str]],
    finished: bool = True,
) -> AuditRunRow:
    run = AuditRunRow(
        started_at=when,
        finished_at=when if finished else None,
        sources_measured=47,
        findings_total=len(findings),
    )
    session.add(run)
    session.flush()
    for source, check in findings:
        session.add(
            AuditFindingRow(run_id=run.id, source=source, check_name=check, detail="detail")
        )
    session.flush()
    return run


def _patch_audit(findings: list[Finding], sources: int = 47):
    return patch("app.audit.task.audit_detail", return_value=(findings, sources))


def _notifications(session: Session) -> list[str]:
    return list(session.execute(select(NotificationRow.message)).scalars().all())


def test_first_run_writes_baseline_and_pushes_once(db_session: Session) -> None:
    findings = [_finding(f"source-{i}", "severity_constant") for i in range(50)]

    with _patch_audit(findings), patch("app.audit.task._pushover_send") as push:
        result = run_audit(db_session, now=NOW)

    assert result == {"sources": 47, "findings": 50, "new": 50, "pushed": 1}
    assert len(db_session.execute(select(AuditFindingRow)).scalars().all()) == 50
    messages = _notifications(db_session)
    assert messages == ["data audit baseline: 50 findings across 47 sources"]
    push.assert_called_once()


def test_unchanged_second_run_pushes_nothing(db_session: Session) -> None:
    _completed_run(db_session, when=NOW - timedelta(days=1), findings=[("gdacs", "severity_shape")])

    with _patch_audit([_finding("gdacs", "severity_shape")]), patch(
        "app.audit.task._pushover_send"
    ) as push:
        result = run_audit(db_session, now=NOW)

    assert result["new"] == 0
    assert result["pushed"] == 0
    assert _notifications(db_session) == []
    push.assert_not_called()
    assert len(db_session.execute(select(AuditRunRow)).scalars().all()) == 2


def test_new_finding_is_pushed(db_session: Session) -> None:
    _completed_run(db_session, when=NOW - timedelta(days=1), findings=[("gdacs", "severity_shape")])
    current = [_finding("gdacs", "severity_shape"), _finding("nasa-firms", "severity_constant")]

    with _patch_audit(current), patch("app.audit.task._pushover_send"):
        run_audit(db_session, now=NOW)

    assert _notifications(db_session) == ["1 new audit findings: nasa-firms severity_constant"]


def test_resolved_finding_is_recorded_not_pushed(db_session: Session) -> None:
    _completed_run(
        db_session,
        when=NOW - timedelta(days=1),
        findings=[("gdacs", "severity_shape"), ("nasa-firms", "severity_constant")],
    )

    with _patch_audit([_finding("gdacs", "severity_shape")]), patch(
        "app.audit.task._pushover_send"
    ):
        run_audit(db_session, now=NOW)

    assert _notifications(db_session) == []
    latest = db_session.execute(
        select(AuditRunRow).order_by(AuditRunRow.started_at.desc())
    ).scalars().first()
    rows = db_session.execute(
        select(AuditFindingRow).where(AuditFindingRow.run_id == latest.id)
    ).scalars().all()
    assert [r.source for r in rows] == ["gdacs"]


def test_crashed_run_is_skipped_as_the_baseline(db_session: Session) -> None:
    """The one case that decides whether this channel survives.

    A crashed run never reached most sources. Diffing against it would make
    every finding it missed look new and page ~50 false positives the next
    morning.
    """
    _completed_run(
        db_session,
        when=NOW - timedelta(days=2),
        findings=[("gdacs", "severity_shape"), ("nasa-firms", "severity_constant")],
    )
    _completed_run(
        db_session, when=NOW - timedelta(days=1), findings=[("gdacs", "severity_shape")],
        finished=False,
    )
    current = [_finding("gdacs", "severity_shape"), _finding("nasa-firms", "severity_constant")]

    with _patch_audit(current), patch("app.audit.task._pushover_send") as push:
        result = run_audit(db_session, now=NOW)

    assert result["new"] == 0
    push.assert_not_called()


def test_findings_total_matches_the_rows_written(db_session: Session) -> None:
    findings = [_finding(f"source-{i}", "severity_constant") for i in range(7)]

    with _patch_audit(findings), patch("app.audit.task._pushover_send"):
        run_audit(db_session, now=NOW)

    run = db_session.execute(select(AuditRunRow)).scalars().one()
    rows = db_session.execute(select(AuditFindingRow)).scalars().all()
    assert run.findings_total == len(rows) == 7
    assert run.finished_at is not None


def test_clean_run_still_writes_a_row(db_session: Session) -> None:
    """"Nothing wrong" and "never ran" must not look the same (#663)."""
    with _patch_audit([]), patch("app.audit.task._pushover_send") as push:
        result = run_audit(db_session, now=NOW)

    run = db_session.execute(select(AuditRunRow)).scalars().one()
    assert run.findings_total == 0
    assert run.finished_at is not None
    assert result["findings"] == 0
    push.assert_not_called()
```

Add `run_audit` to the `app.audit.task` import line at the top of the test file.

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_audit_history.py -v
```

Expected: FAIL — `ImportError: cannot import name 'run_audit'`

- [ ] **Step 3: Implement `run_audit`**

Append to `app/audit/task.py` (and extend its imports):

```python
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.run import audit_detail
from app.db_models import AuditFindingRow, AuditRunRow
from app.watchdog import _persist_notification, _pushover_send


def _last_completed_keys(session: Session) -> set[tuple[str, str]] | None:
    """Findings of the most recent run that finished. None if there is no such run.

    "Completed" rather than "most recent" is load-bearing: a run that crashed
    part-way never reached most sources, and diffing against it would report
    everything it missed as new.
    """
    run_id = (
        session.execute(
            select(AuditRunRow.id)
            .where(AuditRunRow.finished_at.is_not(None))
            .order_by(AuditRunRow.started_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if run_id is None:
        return None
    rows = session.execute(
        select(AuditFindingRow.source, AuditFindingRow.check_name).where(
            AuditFindingRow.run_id == run_id
        )
    ).all()
    return {(source, check) for source, check in rows}


def run_audit(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Measure, record, and say something only if the answer changed."""
    moment = now or datetime.now(UTC)
    previous = _last_completed_keys(session)
    findings, sources_measured = audit_detail(session, now=moment)

    run = AuditRunRow(
        started_at=moment,
        finished_at=moment,
        sources_measured=sources_measured,
        findings_total=len(findings),
    )
    session.add(run)
    session.flush()
    for finding in findings:
        session.add(
            AuditFindingRow(
                run_id=run.id,
                source=finding.source,
                check_name=finding.check,
                detail=finding.detail,
            )
        )

    baseline = previous is None
    new = findings if baseline else new_findings(previous, findings)

    pushed = 0
    if new:
        message = format_message(
            new,
            baseline=baseline,
            findings_total=len(findings),
            sources_measured=sources_measured,
        )
        # Findings are already staged above, so a dead notification channel
        # never costs history.
        if _persist_notification(
            session, source="data-audit", message=message, today=moment.date(), kind="audit"
        ):
            _pushover_send(message)
            pushed = 1

    session.flush()
    return {
        "sources": sources_measured,
        "findings": len(findings),
        "new": len(new),
        "pushed": pushed,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_audit_history.py -v
```

Expected: PASS, all 12 tests.

If `test_first_run_writes_baseline_and_pushes_once` reports `"new": 50` but you expected the baseline path to report 0 — it should be 50. On the first run every finding is genuinely unseen; the baseline flag changes the *message*, not the count. The counters describe reality; the message decides what a human is told.

- [ ] **Step 5: Commit**

```bash
git add app/audit/task.py tests/test_audit_history.py
git commit -m "feat(audit): #669 persist audit runs and push only what changed"
```

---

### Task 4: Wiring — celery task, beat, watchdog registration, Makefile

**Files:**
- Modify: `app/audit/task.py` (add the `job_run`-wrapped body)
- Modify: `app/tasks.py` (celery task + beat entry)
- Modify: `app/watchdog.py` (`JOB_CADENCE_MIN`, `JOB_OUTPUT`)
- Modify: `Makefile` (`data-audit` target)
- Test: `tests/test_watchdog_output.py` (append one test)

**Interfaces:**
- Consumes: `run_audit`, `app.jobs.heartbeat.job_run`, `app.db.get_engine`
- Produces: `app.audit.task.run_audit_job() -> dict[str, int]`, celery task `app.tasks.data_audit`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_watchdog_output.py`:

```python
def test_data_audit_is_watched_on_run_completion_not_findings() -> None:
    """Zero findings is success. Watching findings would page on good news.

    `audit_runs.finished_at` asks the only honest question: did the audit run
    to completion?
    """
    from app.db_models import AuditRunRow

    model, column = JOB_OUTPUT["data-audit"]

    assert model is AuditRunRow
    assert column is AuditRunRow.finished_at
    assert JOB_CADENCE_MIN["data-audit"] == 1440
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_watchdog_output.py -v
```

Expected: FAIL — `KeyError: 'data-audit'`

- [ ] **Step 3: Register in the watchdog**

In `app/watchdog.py`, add to `JOB_CADENCE_MIN` (after `"validator": 1440,`):

```python
    "data-audit": 1440,
```

Add to the `JOB_OUTPUT` dict:

```python
    "data-audit": (AuditRunRow, AuditRunRow.finished_at),
```

Add `AuditRunRow` to the `from app.db_models import (...)` block, keeping it alphabetical — it goes first, before `BrainNarrativeRow`.

Extend the comment block above `JOB_OUTPUT`'s `severity-grade` exclusion note with:

```python
#: `data-audit` is watched on its run row rather than on findings, and that is
#: the same distinction: zero findings is a healthy audit, so watching findings
#: would page precisely when the data got better. `finished_at` advancing means
#: the audit ran to completion, which is the only thing this check can honestly
#: ask about it.
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_watchdog_output.py -v
```

Expected: PASS.

- [ ] **Step 5: Add the `job_run` body**

Append to `app/audit/task.py`:

```python
def run_audit_job() -> dict[str, int]:
    """One nightly sweep, wrapped in the heavy-job lifecycle.

    Through `job_run` rather than called directly: `gather_stats` issues two
    full GROUP BY scans over the events table — 1,290,963 rows and 1151 MB
    measured on 2026-07-29 — which is squarely in the class of job that has to
    let the brain step aside first (#413), and which belongs on the activity
    monitor while it runs.
    """
    from sqlalchemy.orm import sessionmaker

    from app.db import get_engine
    from app.jobs.heartbeat import job_run

    engine = get_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with job_run("data-audit", session_factory=factory):
        with Session(engine) as session:
            result = run_audit(session)
            session.commit()
    return result
```

- [ ] **Step 6: Add the celery task and beat entry**

In `app/tasks.py`, add the task next to the other analytical tasks (near `journal_daily`):

```python
@app.task(name="app.tasks.data_audit")
def data_audit() -> dict[str, Any]:
    """Nightly source-data audit (#669): does each source still mean what it declares?

    Every other guardrail watches presence — that data arrived, that jobs ran,
    that jobs produced something. This is the only one that watches meaning,
    and until now it only ran when someone typed it.
    """
    if skipped := _skip_optional_heavy():
        return skipped
    from app.audit.task import run_audit_job

    return run_audit_job()
```

Add to `app.conf.beat_schedule`, after the `housekeeping-daily-3am-utc` entry:

```python
    "data-audit-daily": {
        "task": "app.tasks.data_audit",
        # 03:40 — last in the nightly window (journal 02:15, validator 02:45,
        # housekeeping 03:00) and specifically after housekeeping runs the
        # retention prune, so findings describe the table as it stands rather
        # than counting rows about to be deleted.
        "schedule": crontab(hour=3, minute=40),
    },
```

`_skip_optional_heavy()` already exists in `app/tasks.py` and returns `{"skipped": True, "reason": ...}` when `runtime_load.busy_reason()` says the box is under load. Keeping it is correct here: two full scans over 1151 MB must not land on top of real work, and a skipped night is not silent — a skip returns before `run_audit_job()` ever runs, so no `job_runs` row is written and `check_jobs` pages after `job_stale_after(1440)` = 2880 minutes (48 h) if it keeps skipping.

- [ ] **Step 7: Add the Makefile target**

Neighbouring targets use the form `.venv/bin/python -m app.<module>.run` (see `journal:` at `Makefile:76` and `briefing:` at `Makefile:136`). Match it — add to the end of `app/audit/task.py`:

```python
if __name__ == "__main__":  # pragma: no cover - CLI entry
    print(run_audit_job())
```

Then add the target next to `briefing:`:

```make
data-audit:  ## Run the source-data audit now and record it in the run history (#669)
	.venv/bin/python -m app.audit.task
```

Note `scripts/data_audit.py` stays exactly as-is: it prints a report and writes nothing, so a hand-run of the *script* never shifts the baseline the next nightly delta compares against. `make data-audit` does write a run — it is the same job the beat runs, just triggered early.

- [ ] **Step 8: Run the full verification gates**

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
```

Expected: all three clean. All must pass — backend CI runs the format check as well as the lint check.

- [ ] **Step 9: Run it once for real against the dev database**

```bash
.venv/bin/python -c "from app.audit.task import run_audit_job; print(run_audit_job())"
```

Expected: a dict like `{'sources': 47, 'findings': 50, 'new': 50, 'pushed': 1}`, and a `data audit baseline: …` notification row. This is the first real run, so it takes the baseline path.

Then confirm the history is queryable:

```bash
docker compose exec -T postgres psql -U osint -d osint \
  -c "SELECT started_at, sources_measured, findings_total FROM audit_runs ORDER BY started_at;"
```

Record the actual numbers — they go in the PR body, and they are the answer to "is it still 50?"

- [ ] **Step 10: Commit**

```bash
git add app/audit/task.py app/tasks.py app/watchdog.py Makefile tests/test_watchdog_output.py
git commit -m "feat(audit): #669 run the source-data audit nightly"
```

---

### Task 5: Squash and open the PR

**Files:** none — git and `gh` only.

- [ ] **Step 1: Confirm the branch is current with main**

```bash
git fetch origin
git rebase origin/main
```

If phantom conflicts appear from squash-merged parents, `git rebase --onto origin/main <old-base> 669-audit-on-a-clock` is the fix, not manual resolution.

- [ ] **Step 2: Re-run the gates after the rebase**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest
```

Expected: clean. Do not open the PR on unverified output.

- [ ] **Step 3: Squash to one commit**

```bash
git reset --soft $(git merge-base origin/main HEAD)
git commit -F - <<'EOF'
feat(audit): #669 put the source-data audit on a clock

#580 built the only check in the system that asks whether the data means what
it claims, and left it running on request. It has been run once: fifty findings
across forty-seven sources, weeks ago, with nothing since to say whether that is
still the number.

Every other guardrail is on a clock and every one of them watches presence —
sources arriving, jobs running, jobs producing output. #663 named the shape:
a component reporting "I am deliberately doing nothing" is invisible to
anything looking for failure. This is that shape one level up. A source can
arrive on schedule, produce rows, pass every liveness check, and emit constant
severity for a month without a word being said.

Nightly rather than watchdog cadence, and through job_run: gather_stats does two
full GROUP BY scans over 1,290,963 rows and 1151 MB, so it is a heavy job that
has to let the brain step aside. 03:40 puts it last in the nightly window and
after housekeeping's retention prune, so findings describe the table as it
stands rather than counting rows about to be deleted.

A snapshot per run rather than an event log, so the trend is a GROUP BY and not
a state machine that can silently lose history. Only findings absent from the
last *completed* run are pushed — the standing fifty have to stay silent or the
channel is noise by the second morning. Completed rather than most recent is
the subtle one: a crashed night never reached most sources, and diffing against
it would page everything it missed.

Watched by #663 on audit_runs.finished_at rather than on findings count. Zero
findings is a healthy audit; watching findings would page when the data got
better.

Detect only. No quarantine, no auto-correction, nothing silently repaired — a
system that quietly fixes bad data produces numbers nobody can audit. Excluding
a source that fails composite_reachability needs this trend data first, and
changes what the composite eats while the composite is under evaluation.
EOF
```

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin 669-audit-on-a-clock
gh pr create --title "feat(audit): #669 put the source-data audit on a clock" --body "$(cat <<'EOF'
Closes #669.

`app/audit` (#580) is the only check that asks what the data *means* rather than
whether it arrived, and the only one that was not on a schedule. This gives it a
clock and a memory.

## What it does

- `audit_runs` + `audit_findings`: one snapshot per nightly run
- runs 03:40 UTC through `job_run()`, last in the nightly window and after the
  retention prune
- pushes only findings absent from the last **completed** run — the standing ~50
  stay silent and recorded
- registered in #663's `JOB_OUTPUT` on `audit_runs.finished_at`, not on findings
  count: zero findings is success

## First real run

<!-- paste the actual dict and the psql output from Task 4 Step 9 -->

## Three deviations from the spec, all deliberate

1. **`check_name`, not `check`** — `CHECK` is reserved in Postgres and this table
   exists to be queried by hand.
2. **Crash signal is a missing row, not a NULL `finished_at`** — the spec
   described both, which would mean two transactions for no gain. `job_runs`
   already records the failure and #663 sees `MAX(finished_at)` stop advancing,
   so the run row is written once at the end with its findings. Column stays
   nullable for the schema-level guarantee.
3. **The script reports, the make target runs.**
   `python scripts/data_audit.py` stays read-only and writes nothing, as the
   spec required. `make data-audit` runs the actual job and does write a run
   row, so a mid-day trigger becomes the baseline the next nightly delta
   compares against. That is what "new since the last completed run" has always
   meant — worth knowing, not worth preventing.

## Not in this PR

Quarantine (excluding a source that fails `composite_reachability` from the
composite) and dashboard publishing. Both want the trend data first, and
quarantine changes what the composite eats while the composite is still the
thing under evaluation.

## Verification

`ruff check` · `ruff format --check` · `pytest` — all clean.
Migration `0022` applied, downgraded, and re-applied against the dev database.
EOF
)"
```

- [ ] **Step 5: Report to Basil and stop**

Tell him the PR number and the first-run numbers. Do **not** watch CI, do not poll, do not merge.

---

## Self-Review

**Spec coverage:**

| spec requirement | task |
|---|---|
| `audit_runs` + `audit_findings` tables | 1 |
| alembic migration, no backfill | 1 |
| `scripts/data_audit.py` stays read-only | 4 (step 7 note) |
| nightly 03:40 through `job_run()` | 4 |
| delta against last *completed* run | 3 |
| first run pushes one baseline line | 3 |
| resolved findings recorded not pushed | 3 |
| detail change alone does not push | 2 |
| message truncation under 1024 chars | 2 |
| `dedup_key` one push per day | 3 (`_persist_notification`, kind="audit") |
| `JOB_OUTPUT` on `finished_at` not findings | 4 |
| kept forever, no prune | 1 (migration docstring; nothing added to housekeeping) |
| 9 tests + 1 watchdog registration test | 1 (1), 2 (4), 3 (7), 4 (1) = 13 total |

No gaps. Test count exceeds the spec's nine because the pure layer split in Task 2 made three cases testable without a database.

**Placeholder scan:** one intentional `<!-- paste … -->` in the PR body, filled from Task 4 Step 9's real output. Every other step carries its actual code.

**Type consistency:** `Finding.check` (dataclass attribute) maps to `AuditFindingRow.check_name` (column) at the single conversion point in `run_audit`. `audit_detail` returns `tuple[list[Finding], int]` in Task 2 and is consumed with that shape in Task 3. `run_audit` returns `dict[str, int]` with keys `sources`/`findings`/`new`/`pushed`, asserted with exactly those keys in Task 3's tests and returned unchanged by `run_audit_job` in Task 4.
