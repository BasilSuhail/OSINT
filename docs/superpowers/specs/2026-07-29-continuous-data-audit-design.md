# Continuous data audit — design

**Issue:** #669
**Date:** 2026-07-29

**As shipped:** this document is a record of intent, not a description of the
final code. Four statements below no longer match what shipped: `finished_at`
nullable (:169) does not defend against a crashed run — `app/audit/task.py`
writes both timestamps together at the end, so a crash leaves no row at all,
not a NULL `finished_at`; the data model (:161) shows `check: Mapped[str]`,
the shipped column is `check_name`; `app/audit/run.py` (:73, :87) is not
unchanged — `audit_detail` was extracted and `audit()` became a delegate; and
the dedup key (:77, :213) is `watchdog:audit:data-audit:{date}`, not
`audit:new:{date}`. See the deviation list at
`docs/superpowers/plans/2026-07-29-continuous-data-audit.md:26-28` for the
reasoning behind the deliberate ones.

## Problem

#580 built the only check in the system that asks whether the data *means* what
it claims — eight rules over 47 declared source expectations, measuring whether
severity is present, varies, parses, and reaches the composite at all.

It runs when someone types `python scripts/data_audit.py`.

It has been run once. It found **50 findings across 47 sources**. That number is
weeks old, and nothing in the system knows whether it is still 50, or 80, or 12.

Every other guardrail watches *presence*, and every one of them is on a clock:

| check | watches | cadence |
|---|---|---|
| `check_sources` | is data still arriving | 15 min |
| `check_footprint_coverage` (#617) | hazard geometry collapsed | 15 min |
| `check_jobs` (#657) | job failing repeatedly | 15 min |
| output watchdog (#663) | job succeeds, produces nothing | 15 min |
| **`app/audit` (#580)** | **does severity vary, parse, reach the composite** | **on request** |

#663's commit named the shape precisely: *"a component that reports 'I am
deliberately doing nothing' is invisible to every check that looks for
failure."* This is the same shape one level up. A source can arrive on
schedule, produce rows, satisfy every liveness check, and emit constant severity
for a month. Nothing in the system would say a word.

## Why it matters analytically, not just operationally

#582 settled the composite as constructed — three pre-registered exams, three
negatives. But README §2.3 is explicit that this does **not** settle the input
question: *"'bad construction' and 'bad inputs' remain indistinguishable from
these results alone."*

#579 (FIRMS stores detection confidence, not intensity, and runs non-monotonic
to fire radiative power) and #580 (severity is a two- or three-level categorical
across nearly every source) are the evidence that inputs are a live suspect.

Separating the two hypotheses needs a findings **trend**. A findings snapshot
cannot do it. That is what this issue builds.

## Scope

**Detect only.** Put the existing audit on a clock and give it a memory.

Explicitly deferred, each to its own issue:

- **Quarantine** — excluding a source that fails `composite_reachability` from
  the composite. Needs trend data first to know what is safe to rest, and it
  changes what the composite eats while the composite is under evaluation.
  Note `source_quarantine` (#567) is a different axis: it rests sources that
  cannot *fetch*. A source that fetches fine and emits garbage is invisible to
  it.
- **Publishing** — findings count on the dashboard beside coverage bias.

**Never in any of them: silent self-repair.** No auto-adjusted severity, no
imputed country, no dropped outliers. A system that quietly fixes bad data
produces numbers nobody can audit, which is the precise opposite of what the
pre-registration machinery exists to protect. The reachable goal is not "the
data is perfect" — it is "every defect is measured, dated, and visible."

## Architecture

```
beat "data-audit-daily" (03:40 UTC, after the retention prune)
  └─ app.tasks.data_audit                 @job_run("data-audit")
       └─ app/audit/task.py
            1. findings = app.audit.run.audit(session)   ← unchanged, pure
            2. persist: 1 audit_runs row + N audit_findings rows, one txn
            3. new = this run's (source, check) − last COMPLETED run's
            4. if new: _pushover_send + NotificationRow
                       dedup_key = "audit:new:{date}"
```

Four steps, each testable alone. `audit()` is already pure and already covered;
steps 2–4 are the only new logic, and step 3 is a set difference.

### Boundaries

| unit | does | depends on |
|---|---|---|
| `app/audit/run.py` | measures | events table. **Unchanged.** |
| `app/audit/task.py` | records + notifies | `run.audit()`, the two models |
| `scripts/data_audit.py` | prints a report | `run.audit()`. **Stays read-only.** |

`scripts/data_audit.py` deliberately does not write a run row. A hand-run
mid-afternoon must not shift the baseline the next nightly delta compares
against.

### Placement

Follows `app/briefing/{run,task}.py` — the repo's existing shape for "analysis
module plus its celery task". Rejected alternatives:

- **Fold into `app/watchdog.py`** — wrong cadence and wrong cost. Watchdog is a
  15-minute liveness sweep; this is a nightly heavy scan. Putting it there means
  either running it 96× a day or writing a scheduler inside a scheduler, and it
  grows a 387-line file already carrying three jobs.
- **System cron outside celery** — loses `job_run()`, so no brain eviction, no
  activity-monitor chip, no `job_runs` row, and #663's output watchdog cannot
  see it.

### Why nightly, and why through `job_run()`

`gather_stats` issues two full `GROUP BY` scans over `events`. Measured on the
live database on 2026-07-29: **1,290,963 rows / 1151 MB**. That is a heavy job
on Pi-class hardware, in the class that must let the brain step aside before it
starts (#413) — not a watchdog-cadence check. #656 is the standing reminder of
what an unbudgeted query costs here.

03:40 UTC places it at the tail of the existing nightly window — `journal-daily`
02:15, `validator-nightly` 02:45, `housekeeping-daily` 03:00 — and specifically
**after** housekeeping, which runs the retention prune. Findings then describe
the table as it actually stands rather than counting rows about to be deleted.
It is last in the window, so it never delays a job that another job waits on.

### Output-watchdog registration

`data-audit` joins #663's `JOB_OUTPUT` keyed on `AuditRunRow.finished_at` —
**not** on findings count. Zero findings is success; watching findings would
page when the data gets better. `finished_at` asks the only honest question:
did the audit run to completion?

## Data model

Two tables, following `JobRunRow` conventions.

```python
class AuditRunRow(Base):
    """One sweep of the source-data audit (#580 machinery, now on a clock).

    The run row exists even when the audit finds nothing. An empty run is the
    healthy state and still has to be visible, or "clean" and "never ran" look
    identical — which is the #663 failure shape.
    """

    __tablename__ = "audit_runs"

    id:               Mapped[int]            # BigIntPK, autoincrement
    started_at:       Mapped[datetime]       # tz-aware, server_default=now()
    finished_at:      Mapped[datetime | None]  # NULL = crashed mid-run
    sources_measured: Mapped[int]            # default 0
    findings_total:   Mapped[int]            # default 0

    __table_args__ = (Index("audit_runs_started_idx", "started_at"),)


class AuditFindingRow(Base):
    """One finding inside one run. Mirrors checks.Finding exactly."""

    __tablename__ = "audit_findings"

    id:     Mapped[int]   # BigIntPK
    run_id: Mapped[int]   # FK -> audit_runs.id, ON DELETE CASCADE
    source: Mapped[str]
    check:  Mapped[str]   # rule name, e.g. "severity_constant"
    detail: Mapped[str]   # the sentence the rule already writes

    __table_args__ = (Index("audit_findings_run_idx", "run_id", "source"),)
```

Decisions inside this:

- **`finished_at` nullable is load-bearing.** A crashed run leaves `started_at`
  set and `finished_at` NULL. The output watchdog reads that as silence and
  pages, mirroring how `JobRunRow` already treats a stale `running`.
- **`findings_total` denormalized onto the run.** The trend is then
  `SELECT started_at, findings_total FROM audit_runs ORDER BY started_at` — no
  join, no aggregate, cheap enough to sit behind an API route later without
  thought. Written in the same transaction as the findings, so it cannot drift.
- **No severity or priority column.** The eight rules do not rank themselves,
  and inventing a ranking here would be a judgement the audit has not earned.
  Add it when there is evidence some checks matter more than others.
- **`check` holds the rule name, `detail` the sentence.** The delta compares
  `(source, check)` — the tuple meaning "this rule objects to this source".
  `detail` carries live counts (`58,793 rows`), so including it in the key would
  page every night as those counts move.
- **Kept forever, no prune.** Follows the storage rule already in force: raw
  events expire at 30 days, derived analytical tables do not. ~50 findings/day
  is ~18k rows/yr, single-digit MB. Pruning it would recreate #586 — the
  retention window eating the history the trend needs.

## Data flow and error handling

Five cases decide correctness.

| case | behaviour | why |
|---|---|---|
| **First run ever** | Write run + findings. Push **one** line: `data audit baseline: 50 findings across 47 sources`. | The standing 50 are not news, they are the starting position. Paging them individually trains the channel to be muted on day one. |
| **Previous run crashed** (`finished_at IS NULL`) | Skip it; diff against the last run that *completed*. | Diffing against a partial run makes every finding it never reached look new. One crashed night would page ~50 false positives the next morning. |
| **No change** | Run + findings written. Nothing pushed. | The standing findings stay silent and recorded. |
| **New finding appears** | Push `2 new audit findings: nasa-firms severity_constant · rss-x country_coverage`. | The entire point of the issue. |
| **Finding resolves** | Recorded by absence from this run's rows. Not pushed. | Good news is not urgent; the trend query shows it. |

Failure modes:

- **`audit()` raises** — the exception propagates, `job_run()` marks the run
  failed, the transaction rolls back, no partial `audit_runs` row survives.
  #657's failure-rate watchdog sees it.
- **Pushover unreachable** — `_pushover_send` already swallows `httpx.HTTPError`
  and logs. Findings are persisted *before* the push, so a dead notification
  channel never costs history.
- **Message overflow** — Pushover caps around 1024 characters and 50 new
  findings would exceed it. Name the first five, then `… +45 more`. The full
  list lives in the table.
- **Stores down / table empty** — every source trips `no_data` and the delta is
  large. Truncation handles the message; the count itself is the honest signal.
- **Re-run by hand the same day** — `dedup_key = "audit:new:{date}"` means one
  push per day regardless of how many times the task fires.

## Testing

TDD, sqlite in-memory, following `tests/test_watchdog_output.py`. The eight
audit rules keep their existing coverage and are not retested here.

`tests/test_audit_history.py`:

| test | asserts |
|---|---|
| `test_first_run_writes_baseline_and_pushes_once` | one run row, N finding rows, exactly one notification, message says "baseline" |
| `test_unchanged_second_run_pushes_nothing` | two run rows, zero new notifications |
| `test_new_finding_pushes_it` | only the new `(source, check)` appears in the message |
| `test_resolved_finding_is_recorded_not_pushed` | absent from run 2's rows, zero notifications |
| `test_crashed_run_is_skipped_as_baseline` | run 2 has `finished_at=None`; run 3 diffs against run 1 |
| `test_detail_change_alone_does_not_push` | same `(source, check)`, different counts in `detail` → silent |
| `test_message_truncates_over_five` | 50 new findings → names 5, says `+45 more`, under 1024 chars |
| `test_findings_total_matches_row_count` | the denormalized counter cannot drift |
| `test_run_row_written_when_no_findings` | a clean run is still visible |

`test_crashed_run_is_skipped_as_baseline` is the regression test that matters —
it is the one case that turns a quiet guardrail into a channel nobody reads.

One addition to `tests/test_watchdog_output.py`: `data-audit` is registered in
`JOB_OUTPUT` against `AuditRunRow.finished_at`.

## Migration

One alembic revision creating both tables. No backfill: the #580 run was a
report, not a persisted run, and inventing a historical run row would date it
falsely. History starts at the first nightly run.

## Success criteria

1. `audit_runs` gains one row per night, unattended.
2. A source whose severity goes constant pages within 24 hours.
3. The standing ~50 findings page zero times after the baseline run.
4. `SELECT started_at, findings_total FROM audit_runs ORDER BY started_at`
   answers "is it still 50?" without anyone typing a script.
5. A crashed audit is visible as silence via #663, not as a false all-clear.
