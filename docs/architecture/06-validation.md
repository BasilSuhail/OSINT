# 06 — Validation

Two senses of "validation":

1. **Methodological validation** — does the multi-modal composite stress index discriminate real instability events across geopolitical, market, and hazard domains? This is covered in detail in [`../methodology.md`](../methodology.md) Part A; this file documents how the architecture supports that protocol.
2. **Runtime validation** — does the system actually work day to day? Health checks, replay, dashboard plausibility tests, snapshot fixtures.

- [Methodological validation hooks](#methodological-validation-hooks)
- [Runtime validation](#runtime-validation)
- [Lead-time gate dry-run](#lead-time-gate-dry-run)
- [Replayability](#replayability)
- [Pre-evaluation checklist](#pre-evaluation-checklist)

---

## Methodological validation hooks

The architecture is built so the pre-registered evaluation can be run cleanly. The hooks below exist specifically for this:

| Need from `methodology.md` Part A | Architectural support |
|---|---|
| Train 2015-2021 / Val 2022 / Test 2023-2024 split | GDELT + market + hazard backfills land in `/mnt/data/parquet/<source>/year=*/month=*/day=*/`; the evaluation reads Parquet directly, never Postgres |
| Hybrid ground truth (ACLED + NBER + IMF + FRED VIX + EM-DAT + GDACS red-alerts), kept separate from inputs | `worker-labels` writes to the `labels` table per [`04-schema.md`](04-schema.md#ground-truth-label-tables) and Parquet partition `/mnt/data/parquet/labels/`; the eval joiner reads `scores` and `labels` separately |
| Nine baselines (B0..B8) | `scores` table keys on `(country, bucket_start, bucket_length, score_name, method_version)` — each baseline is just another `score_name` row, no schema change |
| Per-domain subtasks (geo-only, market-only, hazard-only targets) | Same `labels` table, filtered by `label_code` prefix; same baselines, just evaluated against subsets |
| Method version lock | `method_version` column on `scores` prevents silently changing the methodology mid-evaluation; ablations live as separate versions, not overwrites |
| Sensitivity tests (weight Monte Carlo over Dirichlet, normalisation alternatives, source ablation, country LOOCV) | Composite worker accepts a `WeightingConfig` and `NormalisationConfig`; sensitivity sweep runs the same worker with permuted configs, writes each result as a distinct `method_version` |
| Reproducibility | Parquet archive (events + labels) is the ground source; running the eval today and a year from now gives the same numbers if the harness code is unchanged |

In short, the architecture's job is to make the evaluation **uninteresting to operate**: pull Parquet for events and labels, join on `country` and time bucket, compute metrics, report tables. The interesting work is the methodology, not the data wrangling.

---

## Runtime validation

Day-to-day "does this work" checks. None of these are part of the thesis evaluation; they exist so the system stays trustworthy.

### Health endpoint

`GET /admin/health` returns:

```json
{
  "postgres":    {"ok": true,  "latency_ms": 4},
  "redis":       {"ok": true,  "latency_ms": 1},
  "disk":        {"ok": true,  "free_gb": 6240, "free_pct": 78},
  "raid":        {"ok": true,  "degraded": false},
  "sources": {
    "gdelt":      {"ok": true,  "last_success": "2026-06-17T05:45:00Z", "stale_min": 12},
    "yfinance":   {"ok": true,  "last_success": "2026-06-17T05:55:00Z", "stale_min": 2},
    "fred":       {"ok": true,  "last_success": "2026-06-17T07:00:00Z", "stale_min": 0},
    "usgs-quake": {"ok": true,  "last_success": "2026-06-17T05:57:00Z", "stale_min": 0},
    "gdacs":      {"ok": true,  "last_success": "2026-06-17T05:50:00Z", "stale_min": 7},
    "nasa-firms": {"ok": true,  "last_success": "2026-06-17T05:55:00Z", "stale_min": 2},
    "acled":      {"ok": false, "last_success": "2026-06-16T04:00:00Z", "stale_min": 1556, "reason": "HTTP 503"}
  },
  "method_version_active": "v1.0"
}
```

A staleness threshold per source triggers a Pushover alert routed via `worker-notify`. The dashboard's top bar shows red if any Tier-1 source (Modules A, B, or C, or any ground-truth source) is stale beyond threshold.

### Source-level plausibility tests

Each fetcher ships with a `plausibility_check(events: list[Event]) -> list[str]` returning warnings:

```python
# app/sources/gdelt.py
def plausibility_check(events):
    warnings = []
    if not events:
        warnings.append("empty batch")
    if len(events) > 50_000:
        warnings.append(f"batch unusually large: {len(events)}")
    if all(e.country is None for e in events):
        warnings.append("no country tagged")
    if median(e.severity for e in events if e.severity) > 0.95:
        warnings.append("median severity > 0.95, suspect normalisation drift")
    return warnings
```

Per-domain examples:

- `worker-market`: warn if `yfinance` returns no ticks during US trading hours; warn if FRED last-observation date is older than expected release frequency
- `worker-gdelt`: warn if GDELT zip is < 1 MB (likely partial); warn if zero events tagged for a major country in a 24-h window
- `worker-hazard`: warn if USGS feed returns no events globally for > 6 hours (cron failure more likely than seismic silence); warn if NASA FIRMS hotspot count drops to zero (orbital gap or feed change)
- `worker-labels`: warn if ACLED daily delta is empty across all countries (their API rolled back); warn if a NBER recession declaration appears in the future

Warnings are logged, not raised. They surface on `/admin/health` and Flower. The intent is to catch upstream schema drift (a column dropped, a unit changed) before it pollutes scores or labels.

### Lead-time gate dry-run

Issue #250 defines a phase-1 gate for the sensor-first narrative lead claim.

Run the smoke test from repo root:

```bash
python -m app.backtest.run
```

The command writes one markdown artifact under `docs/backtest/`:

- `docs/backtest/<registry_hash>-report.md`

and prints:

```text
verdict=PASS|FAIL report=docs/backtest/<registry_hash>-report.md
```

This is a manual verification path only; the real gate decision uses the canonical frozen registry and a frozen `events.yaml` hash.

### Dashboard snapshot tests

Frontend has [Playwright](https://playwright.dev/) snapshot tests for:

- Country detail page renders score time series for each of `composite`, `market-only`, `geo-only`, `hazard-only`
- Composite map colours at least one country in the expected range on a fixture date
- Filter toggles persist after reload
- Health panel reads `/admin/health` without error
- Labels view (eval mode) renders the ground-truth overlay correctly

Run on every PR via GitHub Actions, against a Postgres seeded from a small Parquet fixture.

---

## Replayability

The architecture's strongest property: **any composite computation is reproducible from cold storage**.

```
/mnt/data/parquet/yfinance/ ─┐
/mnt/data/parquet/fred/ ─────┤    ┌─── worker-composite (v1.0) ───┐
/mnt/data/parquet/gdelt/ ────┼──> │ normalise → weight → aggregate │ → scores(v1.0)
/mnt/data/parquet/usgs/ ─────┤    └────────────────────────────────┘
/mnt/data/parquet/gdacs/ ────┤
/mnt/data/parquet/firms/ ────┘

                                  ┌─── worker-composite (v1.1) ───┐
                            ────> │ same input, alternative weights│ → scores(v1.1)
                                  └────────────────────────────────┘

/mnt/data/parquet/labels/  ──────────────────────────────────────> eval harness
```

Implications:

- Re-evaluation = `replay --method-version v1.1 --inputs /mnt/data/parquet/...` → writes new score rows; v1.0 scores remain untouched.
- A reviewer asking "what if you used min-max instead of z-score?" can be answered with one command and a follow-up table.
- A claim of cherry-picking is rebutted by showing every version's full results table, not just the favoured one.
- The `labels/` partition is **append-only after lock**. Once `methodology.md` v1.0 is locked with Marco, no rows are deleted; new label sources are added as new `label_source` values, not by rewriting history.

Replay scripts live in `scripts/replay/` and are committed alongside the spec, not invented at evaluation time.

---

## Pre-evaluation checklist

Before the formal evaluation pipeline runs (per [`../methodology.md`](../methodology.md) Part A), all of these must be true:

- [ ] `method_version` for the composite is locked with Marco (v1.0)
- [ ] Historical backfill is complete and verified in Parquet for: GDELT events + GKG (2015-2024), yfinance + FRED time series (2015-2024), USGS Quake (2015-2024), GDACS alerts (2015-2024), NASA FIRMS (2015-2024)
- [ ] Ground-truth backfill is complete and verified for: ACLED (2015-2024), NBER cycle dates, IMF currency-crisis dataset, FRED VIX series, EM-DAT disaster declarations (2015-2024), GDACS red-alert history
- [ ] All nine baselines (B0..B8) are implemented as workers and produce scores into the `scores` table
- [ ] Source-level plausibility checks pass for the full historical backfill, per domain
- [ ] Country panel (20-30 countries, stratified across geo / market / hazard event density) is fixed in `config/country_panel.yaml` and committed
- [ ] Test-set window (2023-2024) is firewalled from training code; verified by a CI grep that no eval module imports test-window data outside the evaluation harness
- [ ] Label-leakage check: confirm no row in `labels` for `bucket_start` before 2015 or after 2024 inclusive of the test window has been read by composite training code

The eval pipeline only runs once on the test window. Crossing items off this checklist is what earns the right to run it.
