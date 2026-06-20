# Data coverage & backfill log

Snapshot of what is in Supabase, how much was backfilled to date, and how
much more we plan to ingest once the Pi + 2 × 4 TB btrfs RAID1 storage
goes online. Kept here so the dissertation chapter on data has a single
source of truth.

> **Why this is a separate doc.** `docs/architecture-spec.md` locks the
> *design* of the storage layer; this file is the *operational record* of
> what actually landed in it.

---

## Storage budget

| Backend | Hard cap | Today |
|---|---|---|
| Supabase free tier (interim demo) | 500 MB row data + 500 MB total | ~130 k rows (~30 MB) |
| Pi btrfs RAID1 (after hookup) | 4 TB usable | TBD |

The retention policy in `app/housekeeping.py` is calibrated for the free
tier — FIRMS pruned at 30 d, GDELT at 90 d, etc. — and will be relaxed
once we move to the Pi (see "After the Pi goes live" below).

---

## Current state (2026-06-20)

**Total events on Supabase: ~127 k.**

| Source | Rows | Country-tagged |
|---|---|---|
| GDELT (geopolitical) | ~91 k | partial — see below |
| NASA FIRMS (active fires) | ~36 k | 97.8 % |
| FRED (macro series) | ~271 | 100 % (by series construction) |
| GDACS (multi-hazard) | ~148 | 100 % |
| EONET (NASA natural events) | ~19 | 100 % |
| USGS (4.5+ quakes daily) | ~19 | 100 % |
| yfinance (country ETFs) | ~43 | 100 % (panel-fixed) |

GDELT looks low for what shows up on the dashboard because the composite
worker only keeps **CAMEO root codes 14–20** (escalatory) — the other ~70 %
of the feed is cooperative behaviour, intentionally filtered out per the
thesis methodology. Country coverage on the historical GDELT rows is
still being backfilled; see "Open backfill task" below.

---

## Backfills run so far

| Date | Source | Window / scope | Rows added | Driver |
|---|---|---|---|---|
| 2026-06-20 | GDELT | 7 days (2026-06-13 → 2026-06-20), concurrency 4 | ~30 k → ~91 k | `scripts/backfill.py --source gdelt --start … --end …` |
| 2026-06-20 | FIRMS, USGS, EONET | country backfill via polygon lookup over historical rows | 97.8 % tagged | `scripts/enrich_country.py` |

Each backfill is **idempotent on `(source, source_event_id)`** so re-running
the same window is safe — duplicate rows are dropped by the unique index.

### Why 7 days, not 2 years

Earlier conversations contemplated a 2-year GDELT backfill (~50 GB) to
warm the rolling-z baseline. Held back deliberately so Supabase free tier
stays well under quota and the demo Pi can be primed with a sensible
snapshot rather than a flood. The bigger backfill happens *after* the Pi
storage is online, see below.

---

## Open backfill task

**Re-enrich GDELT country tags** once #97 (polygon fallback in the
parser) lands on main. The ~91 k historical GDELT rows currently have
country=NULL because they were ingested before the parser fix. Running
`python -m scripts.enrich_country --sources gdelt` will tag them in
batches. Expected ~95 % hit rate.

---

## After the Pi goes live

When the 2 × 4 TB btrfs RAID1 array is mounted on the Pi (see
`docs/architecture-spec.md` § 9), retention windows can be relaxed and
the backfill window opened up:

- **GDELT:** extend to 2 years (~50 GB compressed payload, ~70 k file
  downloads via `scripts/backfill.py`).
- **NASA FIRMS:** keep the per-row payload (currently pruned at 30 d) to
  one year so seasonal fire patterns sit inside the rolling-z window.
- **FRED:** already retained forever; nothing to change.
- **yfinance:** extend ETF lookback to 2 years (cheap; ~10 k rows).

Operational targets to track after the move:

- p50 dashboard read latency from frontend → FastAPI < 300 ms
- Ingest beat lag < 2 × cadence per source over a rolling 7-day window
- Composite scores leave the 0.5 mid-band for ≥ 50 countries
  (currently 0 countries leave the band because rolling-z has no history
  to compare against)

This file is updated whenever a new backfill runs.
