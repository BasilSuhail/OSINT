# ACLED Ground-Truth Labels (P1–P3, labels-v1.0) — Design

**Issue:** #284 · **Part of:** #282 (analytical agenda, roadmap step 1)

## Problem

The `labels` table (`app/db_models.py:106`) exists in the schema but nothing writes or
reads it. Without ground-truth labels the composite score can only be reported, never
graded — no prediction task, no baselines, no thesis result. This is the first blocking
step of the analytical-agenda roadmap.

## Scope

- **In:** geopolitical labels P1–P3 derived from the ACLED aggregate files already on
  disk under `ACLED_CSV_DIR` (`data/private/acled/`). One-shot, idempotent, versioned.
- **Out:** market (P4) and hazard (P5) labels — separate follow-up issues. Panel export
  and baseline evaluation — roadmap steps 2–3.

## Data source

ACLED public aggregate downloads (weekly regional files), already present:

- `*_aggregated_data_up_to_week_of-*.xlsx` — one row per
  (WEEK, COUNTRY, ADMIN1, EVENT_TYPE, SUB_EVENT_TYPE) with EVENTS and FATALITIES.
  Coverage: ~2016 onward for most regions (Africa reaches back further).
- The `number_of_*` country-month/year files are redundant for v1 (weekly regional
  files can be aggregated to months) and are ignored.

Country names are mapped to ISO2 via the existing
`country_name_to_iso2()` (`app/enrichment/country_codes.py:95`). Unmapped names are
logged, counted, and skipped — never guessed.

## Rules (labels-v1.0, aggregate-adapted)

methodology.md Step 2 defines P1–P3 against event-level ACLED rows. Our files are
weekly country aggregates, so the rules are adapted as follows. This adaptation is
recorded as a dated amendment in methodology.md **before any evaluation runs**.

| Code | Rule (aggregate form) |
|---|---|
| `P1` | Any week in the month where `EVENT_TYPE = Battles` fatalities (summed over admin1/sub-event rows) ≥ 10 |
| `P2` | Any week in the month with ≥ 5 demonstration events (`Protests` + `Riots`) AND ≥ 1 `Riots` event (ACLED defines Riots as violent demonstrations / mob violence) |
| `P3` | Country-month political-violence fatalities ≥ 2 × previous month AND current month ≥ 25 fatalities (floor kills 1→2 noise) |

Label granularity: **country-month** (`bucket_start` = month start UTC,
`bucket_length` = 1 month), matching the unit of analysis in methodology.md Step 3 and
the composite aggregation in `app/composite/aggregation.py`.

## Architecture

`app/labels/` package, same discipline as `app/composite/` (import-pure layers,
side effects only at the edges):

| File | Responsibility |
|---|---|
| `acled_loader.py` | Glob + read the weekly regional xlsx files → tidy rows `(country_iso2, week, event_type, sub_event_type, events, fatalities)`. Pure given a file list; pandas + openpyxl (already dependencies). |
| `rules.py` | Pure functions: tidy rows → list of label dicts `{country, bucket_start, label_code, magnitude, payload}`. No I/O, no DB. `RULES_VERSION = "labels-v1.0"`. |
| `persistence.py` | Idempotent upsert into `labels` keyed on `(country, bucket_start, label_code, label_source)`. `label_source = "acled-aggregates"`, payload carries rules version, source file, triggering week(s), raw counts. |
| `run.py` | CLI (`python -m app.labels.run`): load → rules → upsert → print summary (rows per code, countries, date span, unmapped names). `make labels` target. |

`magnitude`: P1/P3 = fatalities, P2 = demonstration event count (per methodology Step 8
magnitude conventions).

## Error handling

- Missing/empty `ACLED_CSV_DIR` → clear message, exit non-zero, no partial writes.
- Unmapped country names → collected and reported in the summary, skipped.
- Malformed rows (missing WEEK/COUNTRY/EVENTS) → skipped, counted.
- Re-run → same rows upserted, no duplicates (unique key above; enforced by
  ON CONFLICT upsert; migration adds the unique constraint).

## Testing (TDD)

- `rules.py`: synthetic dict fixtures — boundary cases 9 vs 10 fatalities (P1),
  4 vs 5 events / zero violent events (P2), exactly-2× and floor 24 vs 25 (P3),
  month bucketing of qualifying weeks.
- `acled_loader.py`: tiny fixture xlsx committed under `tests/fixtures/` — column
  mapping, name→ISO2, malformed-row skip.
- `persistence.py`: upsert idempotency (insert twice → one row), against the test DB
  used by existing persistence tests.

## Migration

One Alembic migration: unique constraint
`labels_country_bucket_code_source_key (country, bucket_start, label_code, label_source)`
to back the idempotent upsert.

## methodology.md amendment

Short dated note in Step 2: P1–P3 operationalised over ACLED aggregate files with the
labels-v1.0 thresholds above; adaptation decided prior to evaluation.
