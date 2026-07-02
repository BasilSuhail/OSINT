# Panel Baselines — Design

**Issue:** #288 · **Part of:** #282 (analytical agenda, roadmap step 3)

## Problem

The panel (#286) exists but nothing is scored against it. Before the composite can
claim anything, the no-skill baselines must be measured — they are the bar. This step
produces the project's first honest evaluation numbers.

## Scope

- **In:** `app/baselines/` + `make baselines` → printed table +
  `$OSINT_DATA_DIR/exports/baselines-report.md` + `.json`.
- **Out:** scoring the composite itself (142 live score rows are not evaluable — the
  report states this and points at #250 backfill), horizons beyond {1,3,6}, plots.

## Task definition (matches methodology.md Step 4)

For each (country, month `t`) in the eval window: predict whether `label_any = 1` for
any month in `[t+1, t+k]`, for `k ∈ {1, 3, 6}`. A row only enters horizon `k`'s
evaluation if all of `[t+1, t+k]` lies inside that country's coverage window (no
truncated horizons).

**Eval window: 2015-01 → 2022-12** (train + validation years). The 2023–2024 test
window stays untouched per the pre-registered protocol — these baselines are
descriptive groundwork, not the final evaluation.

## Baselines (methodology.md Step 5, B0–B2)

| ID | Score at time t | Leakage guard |
|---|---|---|
| `B0` random | seeded uniform [0,1] | none needed |
| `B1` persistence | `label_any(t)` (this month's state as next-window forecast) | uses only month t |
| `B2` base rate | expanding mean of `label_any` over that country's months `≤ t` (includes the current month, so it is never empty) | uses only months ≤ t |

## Metrics (methodology.md Step 6)

Hand-rolled pure functions in `app/baselines/metrics.py` (no sklearn dependency):

- **AUROC** — Mann-Whitney rank formula, tie-aware.
- **AUPR** — average precision (step-wise integration of the PR curve).
- **Brier** — mean squared error of probabilistic score vs outcome.

Degenerate inputs (all-positive / all-negative targets) return None and are reported
as `n/a` rather than crashing or faking 0.5.

## Architecture

| File | Responsibility |
|---|---|
| `app/baselines/targets.py` | Pure: panel records → per (country, t, k) binary target, coverage-respecting. |
| `app/baselines/predictors.py` | Pure: panel records → B0/B1/B2 score per (country, t). |
| `app/baselines/metrics.py` | Pure: (scores, targets) → AUROC / AUPR / Brier. |
| `app/baselines/run.py` | CLI: read `panel.parquet`, build targets + scores, metrics per baseline × horizon, write report. `make baselines`. |

Report also includes: per-code positive rates (P1/P2/P3/any) in the eval window,
row counts per horizon, and an explicit "composite not scored — n=142 live rows,
see #250" section.

## Testing (TDD)

- `metrics.py`: known values — perfect ranking → AUROC 1.0; reversed → 0.0; ties →
  0.5; hand-computed AUPR on a 4-point case; Brier on exact values; degenerate targets → None.
- `targets.py`: horizon window truncation at coverage edge; k=3 catches positive at
  t+3 but not t+4; per-country isolation.
- `predictors.py`: B1 equals current label; B2 expanding mean never looks forward
  (changing future labels never changes score at t); B2 first country month equals
  its own label; B0 deterministic under fixed seed.
- `run.py` covered by real-run verification.

## Verification

`make baselines` on the real panel. Sanity expectations: B0 AUROC ≈ 0.5; B1 well above
0.5 (instability is autocorrelated); B2 strong AUROC (persistent country differences).
Report file exists, numbers match printed table.
