# Historical Signal Backfill (market + hazard) — Design

**Issue:** #302 · **Part of:** #282 (critical path) · **Related:** #250 ·
**Depends on:** #300/#301 (journal hindcast guard) merged first.

## Problem

The composite has no signals before mid-2026: it cannot be scored against the
0.931 base-rate bar, WS-F cannot rank indicators, and the panel's signal columns
are NaN across the whole eval window. This backfill produces historical composite
scores for 2015-01 → 2024-12.

## Scope

- **In:** `app/composite/backfill.py` + `make backfill-signals`. Market (yfinance
  country-ETF drawdowns) + hazard (USGS FDSN quakes ≥ M4.5) → existing composite
  pipeline → `scores` rows, same `method_version` as live (identical formulas),
  components carry `"backfill": true` for provenance.
- **Out:** geopolitical domain (GDELT bulk = heavy; ACLED = circular with labels),
  GDACS/EM-DAT hazard history, evaluating the scores (that is the very next step,
  but a separate run of `make panel && make baselines`).

## Key constraints honoured

1. **Events never touch the events table** — retention pruning would eat them.
   They are built in memory and flow straight through
   `aggregate_events_to_domain_signals → normalize_domain_signals → compute_scores
   → upsert_scores`. Reusing the exact live functions keeps the methodology
   identical by construction.
2. **No live-era overlap** — scores are written only for buckets ≤ 2024-12;
   live rows start 2026. Warmup data from 2014-01 feeds the 12-month rolling
   z-score window so 2015 buckets are properly normalised.
3. **No journal poisoning** — the #300 hindcast guard skips all of these buckets
   at emit time (their windows are long past).
4. **USGS API cap** — 20k rows/query; fetched in yearly chunks (M4.5+ global runs
   ~7-8k/year). Failures on a chunk abort loudly rather than writing a partial
   year silently.

## Components

| Piece | Responsibility |
|---|---|
| `iter_year_chunks(start, end)` | Pure: split a date range into calendar-year chunks. |
| `fetch_market_history(start, end)` | yfinance per COUNTRY_ETFS ticker, full daily history, reusing the live fetcher's `_compute_events` drawdown → severity transform. |
| `fetch_hazard_history(start, end)` | USGS FDSN query per year chunk, `parse_geojson_body` for severity/country, drop countryless rows. |
| `run_signal_backfill(...)` | Compose: fetch both domains → pipeline → filter buckets to [start_scores, end] → upsert. Injectable fetchers for tests. |
| CLI `main()` | Fixed window (warmup 2014-01, scores 2015-01 → 2024-12), summary print. |

## Testing (TDD)

- `iter_year_chunks`: full years, partial edges, single-year range.
- `run_signal_backfill` with injected fake fetchers: scores written to SQLite;
  warmup months excluded from output; no bucket after end; components stamped
  `backfill: true`; rerun idempotent (upsert).
- Hazard chunk failure → raises (no silent partial year).

## Verification

Real run: `make backfill-signals` (minutes — ~40 ETFs × 11y daily + 11 USGS
queries). Then `make panel` → signal coverage jumps from 142 rows to thousands;
spot-check a known event month (e.g. RU 2022-03 market stress). Then
`make baselines` — extended next step: composite AUROC vs the bar (tracked in
the issue, not this PR).
