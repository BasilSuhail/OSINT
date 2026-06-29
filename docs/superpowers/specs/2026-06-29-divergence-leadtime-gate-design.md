# Divergence Lead-Time Gate — Design Spec

> Date: 2026-06-29. Phase-1 gate for the sensor-first pivot (see `POSITIONING-SCRATCH.md` §v2).
> Status: design approved, pre-implementation.

## Purpose

Prove — or kill — the one claim the whole build-to-sell pivot rests on:

> **Physical sensor activity moves before the narrative.** For a real event, the
> physical-activity signal spikes *days before* the news/GDELT volume spikes.

That lead time is the product. If it is real and measurable, the divergence engine
becomes a sellable alt-data signal (customers: event-driven / macro / commodity
funds) and the thesis defense answer ("so what?") is grounded in evidence. If it is
not real, we stop and treat the system as a portfolio/thesis showcase — having
spent the smallest possible effort to find out.

This spec covers **only the gate**: the smallest build that answers the question
honestly. Feed/API, alerting, and assets-overlay are explicitly out of scope
(Phase 2, only if the gate passes).

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Scope | Phase-1 lead-time gate only (decompose the larger build-to-sell roadmap) |
| Domains | Broad multi-domain (leverage existing CII work) |
| Proof target | Signal must **lead the narrative** (physical delta spikes N days before news/GDELT volume) |
| Data scope | Add AIS + VIIRS flaring **with failsafes + source-health panel**; ACLED is Basil's lane |
| Pass bar | **Pre-registered events + median lead** + measured false-positive rate |
| Approach | A — backtest harness over historical normalized data (reusable engine, not throwaway) |

## Hard constraint

**AIS free tier (aisstream.io) is live-only — no history.** It therefore cannot be
part of the *historical* backtest of pre-registered past events. AIS contributes to
the forward-running live signal only. The gate backtest leans on sources that have
history: GDELT (narrative) + FIRMS, USGS, GDACS/EONET, VIIRS flaring (physical).

## Architecture

Layered on the existing pipeline (`fetchers → normalize → event store (Postgres) →
API → map/globe`). No rewrite. The normalization layer (the crown jewel) is
untouched; everything new sits on top of the normalized event store.

```
EXISTING (reuse):  fetchers → normalize → event store → API → map/globe
                                    │
NEW:                                ▼
  1. Sensors        AIS (live WS) + VIIRS flaring (historical+live) → same event schema
  2. Divergence     per country×day: physical_index vs narrative_index → divergence score
  3. Backtest       frozen event registry + historical backfill → lead-time + false-pos report
  4. Source-health  extend ingest_health: status + rate-limit + last-pull
  5. Frontend       SourceHealthPanel
```

### Component boundaries (each independently testable)

- **`app/divergence/`** — import-pure (like `app/cii/scoring.py`): takes per-day
  counts, returns a `DivergenceSeries` dataclass. No I/O. Reused by backtest now,
  live Celery task later.
- **`app/backtest/`** — frozen event registry, historical backfill runner, metrics,
  report generator. Depends on `divergence` + event store.
- **`app/sources/viirs_flaring_fetcher.py`** — pull `Fetcher` (existing contract).
- **`app/sources/aisstream_collector.py`** — new streaming-collector mode (WebSocket,
  does not fit the pull `Fetcher` contract).
- **`app/health/`** (or extension of existing ingest-health) — source status registry.
- **frontend `SourceHealthPanel.tsx`** — read-only status view; folds into existing
  `DashboardSection`.

## Component 1 — Divergence engine

Matches existing CII conventions: import-pure, log-scaling, versioned method string.

**Source partition** — every normalized event tagged one side:
- **Physical** (sensors): FIRMS fires, USGS quakes, GDACS/EONET hazards, VIIRS
  flaring, OpenSky ADS-B, AIS (live-forward only).
- **Narrative** (story): GDELT CAMEO events, RSS news.

**Granularity:** country × day (matches existing country enrichment + CII buckets).

**Math** — per country, per day `d`:
1. `physical_raw[d]` = count physical events; `narrative_raw[d]` = count narrative events.
2. Log-scale each (reuse the `_log_scale` convention) to dampen volume bursts.
3. **Rolling z-score** vs trailing 28-day mean/std → `physical_z[d]`, `narrative_z[d]`
   (standardized anomaly, comparable across countries).
4. **`divergence[d] = physical_z[d] − narrative_z[d]`** — positive = physical moved,
   story hasn't (the alpha).

**Lead-time measurement (the gate):**
- Narrative spike day `D_n` = first day `narrative_z ≥ τ_n`.
- Physical spike day `D_p` = first day `physical_z ≥ τ_p` in the window before `D_n`.
- **`lead = D_n − D_p`** (positive days = physical led the story).
- Thresholds `τ_p`, `τ_n` and the rolling window are frozen in config before any backtest.

**Module shape:** `app/divergence/scoring.py`, returns `DivergenceSeries` (z-series +
divergence + spike days). `DIVERGENCE_METHOD_VERSION = "div.v1"`. Same module feeds
backtest now and the live Celery task later.

**Data flow:**
```
event store ──query counts by country×day×side──► log-scale ──► rolling z ──► divergence series
                                                                                │
                                              backtest: align to event registry ┤
                                              live (later): write score rows ────┘
```

## Component 2 — Backtest harness

**Event registry** (`app/backtest/events.yaml`, frozen before any run):
- ~15–20 events, spread across domains + regions + time (avoid single-region bias).
- Each: `{id, country, date, domain, source_url, notes}`. `date` = when the event
  *physically began* (best estimate), not when news broke.
- Git-tracked, committed once. `frozen_at` timestamp + content hash guards against
  edit-after-first-run. New events → a new registry version, never an in-place edit.

**Backfill runner** (`app/backtest/backfill.py`):
- Per event: pull historical events for that country, window `[date − 45d, date + 15d]`,
  from sources with history (GDELT, FIRMS, USGS, GDACS/EONET, VIIRS flaring). AIS excluded.
- Writes into the event store (or an isolated backtest table) so divergence runs on real rows.
- Idempotent + cached (re-runs do not refetch).

**Metrics** (`app/backtest/metrics.py`):
- Per event: physical spike day, narrative spike day, **`lead`** (days).
- Aggregate: **median lead**, % of events with lead ≥ 1 day, lead distribution.
- **False-positive rate:** scan non-event country×day windows — how often
  `divergence ≥ τ` fires with no registry event nearby. The honesty check.
- Baseline (optional but recommended): shuffle/randomize the physical series and
  confirm the real lead exceeds chance.

**Pass bar (frozen):**
> Median physical lead ≥ 1 day on a **majority** of registry events, AND a
> measurable, reported false-positive rate.

**Report** (`app/backtest/report.py`): markdown + plots → `docs/backtest/<registry-version>-report.md`.
States the gate verdict (PASS / FAIL) explicitly. This artifact is the thesis
evidence and the sales proof. Pass → Phase 2 (feed/alerting). Fail → documented kill.

## Component 3 — New sensors

**VIIRS flaring** (`app/sources/viirs_flaring_fetcher.py`) — fits the pull `Fetcher` contract:
- NASA VNF (VIIRS Nightfire) — daily files, **has history** → usable in backtest.
- Emits one `Event` per flaring detection (lat/lon, radiant heat, country via existing
  enrichment). Physical side. Missing day → skip + report, no crash.

**AIS** (`app/sources/aisstream_collector.py`) — new ingestion mode:
- aisstream.io WebSocket = continuous, live-only → separate long-running collector,
  not a pull `Fetcher`.
- **Aggregate** to per-region/chokepoint vessel-count per time bucket → emit periodic
  summary `Event`s. Physical side, forward-live only (excluded from historical backtest).
- Failsafes: auto-reconnect with backoff, heartbeat, bounded buffer (drop-oldest if
  flush lags), liveness reported to source-health.

**Shared failsafe contract** (every new source):
- Never crash the pipeline — catch + report status, continue.
- Report status to source-health: `online | pulling | failing | rate_limited | last_pull_ts`.
- Credentials via `.env` (aisstream key). Missing key → `disabled`, not an error.

**Scope guard (YAGNI):** AIS aggregates to region counts only — no per-vessel tracking,
no dark-vessel/sanctions detection (Phase 2+). The gate needs only the count signal.

## Component 4 — Source-health observability (extend existing)

Reuse `ingest_health` table + `/ingest-health` API + `watchdog.py` +
`ConnectionIndicator.tsx`. Add what is missing.

**Backend — extend `IngestHealthRow`:**
- New fields: `status` (`online|pulling|failing|rate_limited|disabled`),
  `rate_limit_used` / `rate_limit_max` (nullable), `last_error` (text). `last_pull_ts`
  already available via watchdog's last-success tracking.
- Fetchers report status transitions: start pull → `pulling`; success → `online`;
  HTTP 429 → `rate_limited`; exception → `failing`; missing creds → `disabled`.
- Register new sources (`viirs-flaring`, `aisstream`) in the cadence map + watchdog.
- AIS collector reports liveness via heartbeat (WS connected → `online`, dropped → `failing`).

**API:** extend the `/ingest-health` dict with the new fields. No new route.

**Frontend — `SourceHealthPanel.tsx`:**
- Consumes `/ingest-health` via existing `apiClient.ts` / `queries.ts` pattern.
- Per source row: name, status dot (green/amber/red/grey), last-pull relative time,
  rate-limit bar (if applicable), last-error tooltip.
- Grouped by domain (physical / narrative / market). Folds into existing `DashboardSection`.
- `ConnectionIndicator` stays as the global summary; this panel is the detailed view.

**Scope guard:** read-only panel. No start/stop controls, no config editing from UI.

## Testing strategy

Matches existing pytest + frontend `__tests__` setup. TDD where logic is real
(divergence, metrics, aggregation); test alongside for plumbing (API field, panel render).

- **Divergence module:** golden z-score/divergence values; synthetic series with planted
  lead → assert `lead = N`; edges (flat series, zero-variance window, < 28d warmup).
- **Backtest:** registry loader schema validation + edit-after-frozen rejection (hash
  guard); metrics on synthetic registry with planted leads; backfill idempotency.
- **Sensors:** VIIRS fetcher against recorded sample VNF file (fixture, no live net);
  AIS collector against mock WS messages → aggregation + reconnect/backoff + bounded-buffer drop.
- **Source-health:** status transitions (success / 429 / exception / missing-creds);
  `/ingest-health` returns new fields; `SourceHealthPanel` renders states from mocked API.
- **Gate verification:** the report generates and states PASS/FAIL against the frozen
  bar. Per verification-before-completion: the gate claim comes only from actual report
  output, never asserted.

## Out of scope (Phase 2+, only if gate passes)

- Signal feed / API productization.
- Alerting / notifications on divergence spikes.
- Assets / portfolio overlay (CSV import → per-asset alerting).
- AIS dark-vessel / sanctions-evasion detection.
- Market-move and labeled-event-catalog proof targets (this spec proves narrative-lead only).

## Success criteria

1. Divergence engine computes per-country×day divergence + spike days from the
   existing normalized store.
2. Frozen event registry (~15–20 events) committed with hash guard.
3. Backtest backfills history, runs divergence, produces a report with median lead,
   % events leading, and false-positive rate.
4. VIIRS flaring fetcher + AIS collector ingest with failsafes; both visible in the
   source-health panel with correct status.
5. The report states an explicit, honest PASS/FAIL verdict against the frozen pass bar.
