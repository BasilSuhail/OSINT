# 03 — Ingestion Pattern

How data flows in: Celery queues, the fetcher contract, dedup, retry, rate limiting, and the schedule.

- [Two queues](#two-queues)
- [Per-source fetcher contract](#per-source-fetcher-contract)
- [Dedup](#dedup)
- [Rate limiting](#rate-limiting)
- [Retry and dead-letter](#retry-and-dead-letter)
- [Schedule (Celery Beat)](#schedule-celery-beat)
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
| OpenSky state | `f"{icao24}:{time_position}"` |
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

Beat is declarative. All schedules live in one file so they are auditable:

```python
# app/celery_beat.py
beat_schedule = {
    "yfinance":      crontab(minute="*/5"),
    "fred":          crontab(hour=7, minute=0),
    "finbert-rss":   crontab(minute="*/30"),
    "gdelt-events":  crontab(minute="0,15,30,45"),
    "gdelt-gkg":     crontab(minute="0,15,30,45"),
    "acled":         crontab(hour=4, minute=0),
    "composite":     crontab(minute="*/60"),
    "housekeeping":  crontab(hour=3, minute=0),
    # Layer 3
    "opensky":       crontab(minute="*"),
    "ais":           "websocket",          # not Beat — long-running consumer task
    "usgs-quake":    crontab(minute="*"),
    "nasa-firms":    crontab(minute="*/2"),
    "celestrak-tle": crontab(hour="*/6", minute=0),
}
```

WebSocket consumers (AISStream) are not Beat-driven; they run as their own systemd-managed worker with auto-reconnect.

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
