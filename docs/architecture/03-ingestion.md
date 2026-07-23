# 03 — Ingestion Pattern

How data flows in: Celery queues, the fetcher contract, dedup, retry, rate limiting, and the schedule.

- [Two queues](#two-queues)
- [Per-source fetcher contract](#per-source-fetcher-contract)
- [Dedup](#dedup)
- [Rate limiting](#rate-limiting)
- [Retry and dead-letter](#retry-and-dead-letter)
- [Schedule (Celery Beat)](#schedule-celery-beat)
- [Runtime backpressure](#runtime-backpressure)
- [Raw archive write](#raw-archive-write)
- [Observability](#observability)

---

## Two queues

| Queue | Cadence | Concurrency | Use |
|---|---|---|---|
| `fast` | ≤ 5 min | 1 worker, 4 child processes | Finance ticks, RSS polls, OpenSky |
| `slow` | ≥ 15 min, batch-heavy | 1 worker, 2 child processes | GDELT 15-min export, FinBERT batch, ACLED daily, housekeeping |

Two queues, not one, because a 30-second GDELT zip parse should never delay a 1-second yfinance call. Each queue runs in its own Celery worker process, scheduled by systemd units `celery-fast.service` and `celery-slow.service`.

Worker resource limits set via systemd:
- `MemoryMax=1500M` per worker (leaves room for Postgres + Redis + FastAPI)
- `CPUQuota=200%` (Pi 5 has 4 cores; 2 cores per worker max)

---

## Per-source fetcher contract

Every fetcher follows the same shape, regardless of source. This is the discipline that lets Layer 3 grow without touching the core.

```python
# app/sources/base.py
from datetime import datetime
from pydantic import BaseModel

class Event(BaseModel):
    source: str               # "gdelt", "yfinance", "opensky", ...
    source_event_id: str      # source-specific stable id (used for dedup)
    occurred_at: datetime     # event time (NOT fetch time)
    fetched_at: datetime
    category: str             # "geopolitics" | "finance" | "weather" | ...
    severity: float | None    # 0..1, source-normalised; None if source has no severity
    keywords: list[str]
    confidence: float | None  # 0..1; None if source does not provide
    location: dict | None     # {"country": "UA", "lat": .., "lon": ..} when applicable
    payload: dict             # full source-specific record (kept for replay)


class Fetcher:
    name: str
    queue: str                # "fast" or "slow"

    def fetch(self) -> list[Event]:
        """Pure function. Return canonical Event list. No DB writes."""
        raise NotImplementedError

    def archive_path(self) -> str:
        """Return the Parquet partition path for this fetcher's events."""
        raise NotImplementedError
```

A Celery task wraps the fetcher:

```python
# app/celery_app.py
@app.task(queue="fast", autoretry_for=(httpx.HTTPError,), retry_backoff=True, max_retries=5)
def run_fetcher(fetcher_name: str):
    fetcher = get_fetcher(fetcher_name)
    events = fetcher.fetch()
    write_raw(events, fetcher)         # always, even on partial failure
    inserted = upsert_events(events)   # idempotent
    return {"fetched": len(events), "inserted": inserted}
```

Fetchers are **pure**: no DB, no Redis, no side effects. The task is the only place that touches state. This makes fetchers unit-testable against recorded HTTP fixtures.

---

## Dedup

Single rule: every event has a stable `(source, source_event_id)` pair. Inserts go through:

```sql
INSERT INTO events (source, source_event_id, ...) VALUES (...)
ON CONFLICT (source, source_event_id) DO NOTHING;
```

The `UNIQUE INDEX events_source_id_idx (source, source_event_id)` enforces it.

Per-source dedup-key recipe:

| Source | `source_event_id` |
|---|---|
| GDELT events | `GLOBALEVENTID` |
| GDELT GKG | `GKGRECORDID` |
| yfinance tick | `f"{symbol}:{timestamp_ms}"` |
| FRED series obs | `f"{series_id}:{date}"` |
| FinBERT-on-RSS | sha256 of `(rss_guid + model_version)` |
| ACLED | ACLED `event_id_cnty` |
| OpenSky density | `f"{iso_country}\|{hour}"` |
| AISStream | `f"{mmsi}:{timestamp}"` |
| USGS Quake | USGS event `id` |
| NASA FIRMS | sha256 of `(lat,lon,acq_date,acq_time,satellite)` |
| CelesTrak TLE | `f"{norad_id}:{epoch}"` |

If a source has no stable ID, hash the canonical fields. Document the recipe in the fetcher source file, not in folk memory.

---

## Rate limiting

Token bucket per source, backed by Redis (`SET key val NX EX`). A fetcher cannot exceed the bucket; it blocks (with timeout) or returns empty.

Why per source, not per worker: many sources publish global rate limits (OpenSky 4000 req/day anon, 8000 with key). A bucket keyed by source survives worker restarts and prevents accidental burn through the daily allowance.

Bucket config lives in `app/sources/<name>.py`:

```python
class OpenSkyFetcher(Fetcher):
    name = "opensky"
    queue = "fast"
    rate_limit = TokenBucket(capacity=10, refill_per_sec=1/6)  # 1 req / 6 s
```

---

## Retry and dead-letter

Celery decorator handles the easy case:

```python
@app.task(
    autoretry_for=(httpx.HTTPError, asyncio.TimeoutError),
    retry_backoff=True,        # 1, 2, 4, 8, 16 s
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
)
def run_fetcher(...): ...
```

After 5 failed retries the task lands in dead-letter:

1. The exception + last response body is written to `ingest_failures` table.
2. A row is added to `dead_letter_queue` with `replay_after` (default: 6 h).
3. `worker-housekeeping` picks up replayable rows every hour and re-enqueues.

This means transient outages (API down for 2 hours) recover automatically. A persistent break (API schema changed) shows up as a non-replayable row that requires human attention, surfaced in the dashboard's `/admin/health` route.

---

## Schedule (Celery Beat)

Beat is declarative. All schedules live in `app/tasks.py` so they are auditable. Active sources as of the source-expansion batch (#157 / #159 / #161 / #163 / #165):

| Source slug | Cadence | Queue | Category |
|---|---|---|---|
| `yfinance` | every 5 min | `fast` | market |
| `fred` | daily 07:00 UTC | `slow` | market |
| `gdelt` | every 15 min | `slow` | geopolitical |
| `usgs-quake` | every 15 min, offset +2 m | `fast` | hazard |
| `gdacs` | every 15 min, offset +4 m | `fast` | hazard |
| `nasa-firms` | hourly | `slow` | hazard |
| `eonet` | every 30 min | `slow` | hazard |
| `rss-*` × 25 | hourly, staggered by feed index | `slow` | news |
| `uk-police` | daily 06:00 UTC | `slow` | news/crime |
| `opensky-adsb` | hourly | `fast` | tracking |
| `abuse-ch-urlhaus` | every 15 min | `slow` | cyber |
| `abuse-ch-feodo` | every 15 min, offset +3 m | `slow` | cyber |
| `polymarket` | every 30 min | `slow` | market |
| `compute_composite` | hourly @ minute 10 | — | scoring |
| `compute_cii` | hourly @ minute 25 | — | scoring |
| `ingest_watchdog` | every 15 min | — | observability |
| `run_housekeeping` | daily 03:00 UTC | — | retention |

`ingest_watchdog` checks two different things. **Staleness**: a source whose
`last_success` is older than `cadence x STALE_MULTIPLIER`. **Footprint
coverage**: the share of GDACS hazard rows old enough to have been enriched
that actually carry `payload.footprint_geojson`, ignoring rows stamped
`footprint_checked_at` (upstream has no geometry for those, which is normal).
Coverage exists because staleness alone missed #604 completely — GDACS kept
answering on cadence for weeks while every refresh deleted the geometry behind
it, so ingest health stayed green while the map drew synthesized circles.

The 25 RSS feeds are not enumerated individually — they're generated from `app/sources/rss_feeds.json` via `feed_cadence_map()` (issue #158). Adding a new feed = one JSON entry.

WebSocket consumers (none active yet — AIS deferred to a follow-up issue) would run as their own systemd-managed worker with auto-reconnect rather than via Beat.

---

## Runtime backpressure

Local model work is the tightest resource constraint on Mac/Pi-class systems.
`brain-qa-eval` writes a heartbeat lock at `data/runtime/busy.json` while it is
running. Optional expensive Celery work checks that lock and exits with
`{"skipped": true, "reason": ...}` instead of competing for CPU/RAM. The API,
frontend, stores, watchdog, and source fetchers remain live, so this is a
degraded full-system mode rather than an eval-only mode.

The default lock TTL is `RUNTIME_BUSY_LOCK_TTL_S=1800`; a stale lock is ignored
automatically. Footprint enrichment is also routed to the serialized analytics
worker and defaults to `FOOTPRINT_ENRICHMENT_LIMIT=25`, because the upstream
geometry fetches are optional and can otherwise dominate a small box.

Local `make up` starts the fetcher worker at `CELERY_CONCURRENCY=1` unless
overridden. Bigger machines may raise it, but the Pi/default profile preserves
headroom for Postgres, Redis, Next, FastAPI, and Ollama.

---

## Raw archive write

Every successful fetch writes the unmodified source response to `/mnt/data/raw/<source>/<timestamp>.<ext>` before the parsed events touch Postgres. Reasons:

- Replay: schema change in `Event` model → re-parse the raw archive, no re-fetch
- Audit: examiner asks "did you really get GDELT at 06:00 on 17 June?" → file is there
- Debugging: if the parser breaks, the raw is still pristine

`raw/` is the only directory that is write-once. Retention is 90 days hot, then off-site only via restic.

---

## Observability

- **Structured logs**: every task logs `{task, fetcher, status, fetched, inserted, duration_ms, error}` as JSON, ingested by `journalctl --output=json`.
- **Flower** ([flower-docs](https://flower.readthedocs.io/)) on `:5555` behind Tailscale, shows live queue depth, task rates, failures.
- **`ingest_health` table**: one row per fetcher per day with success count, failure count, last success at. Dashboard `/admin/health` reads this.
- **Prometheus exporter**: added in Layer 3 once Pi 5 has headroom; thesis-period uses Flower + log-grep.
