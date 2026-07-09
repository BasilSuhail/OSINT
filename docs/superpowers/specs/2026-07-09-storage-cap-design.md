# Storage cap + 30-day retention — design

**Date:** 2026-07-09
**Status:** approved (Basil, 2026-07-09)

## Problem

The stack collects continuously. Target deploy box (Dokploy now, Raspberry Pi
later) has ~40 GB disk; the laptop also runs the stack for days at a time and
must not be overcrowded. Current retention windows (2–7 days) keep the DB tiny
but throw away history the analytical agenda needs, and nothing guards against
a source suddenly out-producing the windows (OpenSky ADS-B already writes
~1 M rows ≈ 650 MB/day including indexes — 94 % of all rows).

## Decision (Basil's rule)

Two rules, identical in every environment. No per-environment behavior.

1. **Time rule:** keep ~30 days of events, delete older.
2. **Size rule:** the database never uses more than 30 GB of disk. Over cap →
   delete oldest data first. No other rules.

## Design

### 1. Settings (`app/settings.py`)

- Retention defaults raised: `retention_gdelt_days` 2→30,
  `retention_news_days` 3→30, `retention_hazard_days` 2→30 (all already
  env-overridable via `RETENTION_*_DAYS`).
- New: `storage_cap_gb: int = 30` (env `STORAGE_CAP_GB`).
- New: `storage_cap_floor_days: int = 7` (env `STORAGE_CAP_FLOOR_DAYS`) —
  size-cap enforcement never deletes events newer than this, so a
  misconfigured cap cannot empty the DB.
- `uk-police` hardcoded 7 → 30 in `retention_days()`; `yfinance` stays 30;
  `fred` and `emdat` stay exempt (`None`, irreplaceable, negligible size).

### 2. Size-cap enforcement (`app/housekeeping.py`)

New `enforce_size_cap(session, *, now) -> dict` running **after** the
retention pass inside the same daily 03:00 UTC housekeeping job.

Algorithm:

- `size = pg_database_size(current_database())`; if `size <= cap` → no-op
  (expected normal case: 30 days ≈ 20 GB steady state).
- Over cap → delete oldest **whole days** of events until estimated freed
  bytes ≥ overage:
  - Per-day footprint estimated from
    `pg_total_relation_size('events') / live_row_count × rows_in_that_day`
    (heap + indexes + toast per row, applied to actual per-day row counts).
  - Days deleted oldest-first by `occurred_at::date`.
  - Hard floor: never delete rows with `occurred_at >= now - floor_days`.
  - `fred` and `emdat` rows exempt from cap deletion too.
- **Never loop on the size reading.** `pg_database_size` reports file
  high-water mark which does not drop after `DELETE`; a
  "while size > cap: delete" loop would delete everything down to the floor.
  Delete a calculated number of days once per run instead.
- After deletion: `VACUUM (ANALYZE) events` so the freed space is internally
  reusable (requires an autocommit connection — VACUUM cannot run inside a
  transaction block).
- Audit: one `housekeeping_runs` row, `job_name="size-cap"`, deleted count,
  notes = size before, cap, days trimmed. A no-op run writes no row.

Error handling: retention runs first; cap enforcement is wrapped so its
failure is logged (audit/notes) but never fails the retention task. VACUUM
failure is non-fatal.

### 3. Wiring (`app/tasks.py`)

Housekeeping task: retention pass → `enforce_size_cap`. Same beat schedule,
no new task.

### 4. Config + docs

- `env.example`: add `STORAGE_CAP_GB`, `STORAGE_CAP_FLOOR_DAYS`, refresh
  `RETENTION_*_DAYS` comments/defaults.
- `docs/storage.md`: retention table now shows 30-day windows; new section on
  the size cap; explicit note on Postgres high-water behavior — after the DB
  peaks, disk usage plateaus rather than shrinking; growth stops, files do
  not shrink. `make data-reset` remains the way to reclaim disk.

## Accepted consequences

- Laptop left running for days grows toward ~20 GB and never past ~30 GB of
  DB files. This is intended ("30 GB is enough").
- 30 GB DB + OS (~4 GB) + Docker images (~4 GB) + WAL/Redis/logs (~2 GB)
  ≈ 40 GB exactly on the target box — tight. Cap is env-overridable; on the
  real server set `STORAGE_CAP_GB=26` for headroom. Default stays 30.
- No archive step. Data older than the window is gone (manual
  `scripts/snapshot.py` remains available before risky changes).

## Testing

Unit tests for cap math with mocked sizes/row counts:

- under cap → no-op, no audit row, no deletes;
- over cap → correct oldest-day selection and day count for the overage;
- floor honored — rows newer than `now - floor_days` survive any cap;
- `fred`/`emdat` rows survive both retention and cap;
- retention pass unaffected when cap enforcement raises.

Retention window tests updated for the new 30-day defaults.

## Out of scope

Partitioned events table (DROP-partition retention), archive-to-parquet
before prune, log rotation, Docker image pruning on the host.
