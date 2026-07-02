# Country-Month Panel Export — Design

**Issue:** #286 · **Part of:** #282 (analytical agenda, roadmap step 2)

## Problem

Labels now exist (#284) and scores accumulate, but every analysis would have to re-join
them from Postgres. The thesis needs one canonical dataset artifact: a country-month
panel that every statistic, baseline, and chart loads from a single file.

## Scope

- **In:** `app/panel/` package + `make panel` → `$OSINT_DATA_DIR/exports/panel.parquet`
  + `panel.csv` + `panel-meta.json`.
- **Out:** any statistics on the panel (roadmap step 3+), historical signal backfill
  (#250), frontend.

## Panel definition

**Spine**: one row per (country, month) inside that country's ACLED coverage window —
first observed ACLED month → last, per country, derived by reusing
`app.labels.acled_loader.load_acled_weekly` (same files the labeler reads). Months
inside coverage with no label are true negatives; months outside coverage are absent
rather than fake zeros (uneven regional file start dates would otherwise pollute the
negative class).

**Columns**:

| Column | Source | Notes |
|---|---|---|
| `country` | spine | ISO2 |
| `month` | spine | month start, UTC date |
| `label_p1` / `label_p2` / `label_p3` | labels table | 0/1 |
| `label_any` | derived | max of the three |
| `magnitude_p1` / `_p2` / `_p3` | labels table | NaN when label absent |
| `signal_market` / `signal_geopolitical` / `signal_hazard` | scores table `components` JSON | NaN where never computed |
| `composite_score` | scores table `score_value` | primary `method_version` only |
| `method_version` | scores table | version stamp of the score row |

Score rows are monthly buckets filtered to `score_name = 'composite'` (the default in
`app/composite/scoring.py:50`). If several method versions exist, export the default
(`app.composite.config.DEFAULT_METHOD_VERSION`).

**Signal gap is intentional**: signals only exist since live deployment (~Jun 2026).
The panel documents the gap honestly — that is the motivating evidence for #250
historical backfill.

## Architecture

| File | Responsibility |
|---|---|
| `app/panel/spine.py` | Pure: tidy ACLED rows → per-country month ranges → grid rows. |
| `app/panel/assemble.py` | Pure: grid + label dicts + score dicts → panel records (list of dicts, pandas-ready). |
| `app/panel/export.py` | DataFrame construction, dtype enforcement, parquet + csv + meta json writes. |
| `app/panel/run.py` | CLI: read DB (labels, scores) + ACLED files → assemble → export → print summary. `make panel`. |

Export overwrites in place — the DB is the source of truth, the export is reproducible;
`panel-meta.json` carries `generated_at`, row/label counts, rules/method versions, and
coverage span so any analysis can cite exactly which panel build it used.

## Dependencies

`pyarrow` added to pyproject (approved). pandas already present.

## Error handling

- Missing ACLED dir → same loud failure as the labeler (spine needs coverage).
- Empty labels table → export still runs (all-negative panel) but summary warns.
- Empty scores table → signal columns all-NaN, summary notes it (expected today).
- Export dir created if absent.

## Testing (TDD)

- `spine.py`: per-country windows differ; month iteration over year boundaries; single-month country.
- `assemble.py`: label join hit/miss, `label_any` derivation, magnitude NaN, score join by month, unmatched score months ignored (outside coverage).
- `export.py`: parquet round-trip preserves dtypes (dates, floats, ints); meta json contents.
- CLI covered by real-run verification, not unit tests (matches `app/labels/run.py`).

## Verification

Real run: `make panel` → row count ≈ Σ per-country coverage months; Ukraine 2022-02 row
has `label_any = 1`; parquet loads in a fresh interpreter with correct dtypes.
