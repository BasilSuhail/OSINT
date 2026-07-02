# WS-D Coverage-Bias Table — Design

**Issue:** #290 · **Part of:** #282 (analytical agenda, WS-D)

## Problem

Media and event data attention is wildly uneven across countries. A composite that
treats raw event volume as signal inherits that bias. WS-D measures the skew and
publishes per-country baselines so later scoring can judge each country against its
own history instead of against louder countries.

## Scope

- **In:** `app/coverage/` + `make coverage` → `$OSINT_DATA_DIR/exports/coverage-bias.md`
  + `.json` + `.csv`, computed from the ACLED weekly regional aggregates (the richest
  history on hand, same files the labeler reads).
- **Out:** live news-volume bias (events table has only weeks of history — revisit
  once meaningful), applying the normalisation inside any score (later work), WS-F
  indicator ranking (blocked on #250 signals, recorded in the issue).

## Table definition

One row per country (ISO2, same loader + alias handling as `app/labels/`):

| Column | Meaning |
|---|---|
| `coverage_months` | months between first and last observed ACLED month (inclusive) |
| `observed_months` | months with ≥1 event row (gaps show reporting dropouts) |
| `total_events` | Σ EVENTS across all rows |
| `events_per_month` | total_events / coverage_months |
| `global_share` | country's fraction of global total events |
| `fatalities_per_event` | Σ FATALITIES / Σ EVENTS (severity-vs-attention lens) |
| `baseline_std` | population std of monthly event volume (`events_per_month` doubles as the baseline mean; 0.0 for single-month countries) |

Summary block: total countries, global events, and concentration — share of global
event volume absorbed by the top 5 / top 10 / top 20 countries.

## Architecture

| File | Responsibility |
|---|---|
| `app/coverage/stats.py` | Pure: tidy weekly rows → per-country stats dicts + concentration summary. |
| `app/coverage/run.py` | CLI: load ACLED files (reuse `app.labels.acled_loader`), compute, write md/json/csv, print summary. `make coverage`. |

No DB access needed — this is a pure file-to-file computation.

## Testing (TDD)

`stats.py` only (run.py by real-run verification):
- coverage vs observed months with a gap month
- events_per_month and global_share arithmetic on a 2-country fixture
- baseline mean/std hand-computed; single-month country → std 0.0
- fatalities_per_event with zero events guarded
- concentration: top-1 share on a skewed fixture

## Verification

`make coverage` on real files. Sanity: global_share sums to 1.0 (±ε); a known loud
country (e.g. Syria/Ukraine) in the top block; md/csv/json row counts equal.
