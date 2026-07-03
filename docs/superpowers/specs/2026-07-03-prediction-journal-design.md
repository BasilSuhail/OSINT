# WS-E Forward Prediction Journal — Design

**Issue:** #292 · **Part of:** #282 (analytical agenda, WS-E)

## Problem

"The dashboard showed it after it happened" is reporting. A thesis needs forecasting
with a scoreboard. The journal logs every forecast with a server timestamp before the
outcome is known, grades it once the window matures, and accumulates an honest
track record. Value scales with runtime — starting late is unrecoverable.

## Scope

- **In:** `predictions` table (migration 0004), `app/journal/` package, daily beat
  task, `make journal` scoreboard + `$OSINT_DATA_DIR/exports/prediction-journal.md`.
- **Out:** alerting/notifications, frontend, non-composite prediction sources (the
  divergence engine can join later via the same `source` column).

## Integrity model (the core of WS-E)

1. **Server-stamped issuance** — `issued_at` has a DB `now()` default; the
   application cannot backdate a forecast.
2. **Immutability** — insert uses ON CONFLICT **DO NOTHING** on
   `(source, method_version, country, bucket_start, horizon_months)`. Re-running the
   composite with revised data can never rewrite an already-issued prediction.
3. **Grading only mutates** `outcome` + `graded_at`, exactly once
   (`WHERE outcome IS NULL` guard in the update).
4. **No hindcasts** (added in #300): a score whose bucket month predates the
   issuance month is never journaled — the full window [t+1, t+k] must lie in
   the future when the forecast is stamped, otherwise grading would fake a
   track record from already-known outcomes.

## Table (migration 0004 + `PredictionRow`)

| Column | Notes |
|---|---|
| `id` | PK |
| `source` | e.g. `composite` |
| `method_version` | e.g. `v1.0` |
| `country` | ISO2 |
| `bucket_start` | month t the forecast is made *from* |
| `horizon_months` | 1 / 3 / 6 — forecast covers [t+1, t+k] |
| `score` | [0,1] probability-like forecast |
| `issued_at` | server default now() |
| `outcome` | null until graded, then 0/1 |
| `graded_at` | null until graded |
| `payload` | components snapshot for audit |

Unique: `(source, method_version, country, bucket_start, horizon_months)`.

## Components

| File | Responsibility |
|---|---|
| `app/journal/emit.py` | Pure: composite score dicts → prediction dicts (k ∈ {1,3,6}); DB fn: insert-if-absent, returns issued count. |
| `app/journal/grade.py` | Pure: prediction + label set + coverage windows → outcome or None (pending). DB fn: grade all pending, once each. |
| `app/journal/scoreboard.py` | Pure: prediction rows → per source × horizon stats (issued, graded, pending, hit rate, Brier, mean score). |
| `app/journal/task.py` | `_journal_daily_body`: emit from scores table + grade gradable. Thin task + beat entry in `app/tasks.py` (daily, after composite hours). |
| `app/journal/run.py` | CLI: run body once, print scoreboard, write report. `make journal`. |

## Grading rule

A prediction (country, t, k) is gradable when:
- every month of [t+1, t+k] is **fully in the past** (month end < now), and
- every month of [t+1, t+k] lies inside the country's label coverage window
  (derived from the ACLED files via `app.labels.acled_loader` — the labels table
  stores only positives, so coverage must come from the source files).

Outcome = 1 if any labels-table row (P1/P2/P3) exists for the country in the window,
else 0. Predictions outside coverage stay pending forever rather than being graded
against unknowable truth (counted as `ungradable` in the scoreboard when the window
is past but uncovered).

## Testing (TDD)

- `emit.py` pure: one score row → three horizon predictions, score carried, payload
  snapshot; DB: insert twice → count once, original score survives a changed rerun.
- `grade.py` pure: positive in window → 1; empty window inside coverage → 0; window
  not yet past → None; window past but outside coverage → None; DB: grade twice →
  `graded_at` unchanged on second pass.
- `scoreboard.py`: hand-computed hit rate + Brier on a small fixture, pending split.

## Verification

`make journal` real run: ~142 composite scores × 3 horizons issued; all pending
(windows in the future — correct, that is the point of a forward journal);
scoreboard prints; beat entry visible in `celery inspect`-style config check
(assert schedule key exists in a test).
