# Local Off-Grid Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Supabase entirely; run the stack local + off-grid with all persistent data in one configurable folder and a local FastAPI read-API feeding the frontend.

**Architecture:** Backend keeps its SQLAlchemy → local Postgres path. A new FastAPI app (`app/api.py`) serves `/events`, `/scores`, and an SSE `/stream`. Persistence publishes a Redis tick on insert; `/stream` forwards it; the frontend backfills via REST. Docker volumes become bind mounts under `OSINT_DATA_DIR`.

**Tech Stack:** Python 3.14, FastAPI, uvicorn, SQLAlchemy 2, Redis (pub/sub), Celery; Next.js 16, React 19, SWR, Zustand, EventSource (SSE).

## Global Constraints

- No new backend dependencies — `fastapi`, `uvicorn[standard]`, `redis`, `sqlalchemy` already in `requirements.txt` / `pyproject.toml`.
- No new frontend dependencies; **remove** `@supabase/supabase-js`.
- Backend tests run against in-memory SQLite via the `db_session` fixture (`tests/conftest.py`). No docker required for unit tests.
- Retention defaults unchanged unless env overrides set: GDELT=2, news=3, hazard=2.
- `OSINT_DATA_DIR` default `./data` (already gitignored).
- Frontend API base from `NEXT_PUBLIC_API_URL`, default `http://localhost:8000`.
- Conventional Commits. One logical change per commit. Never merge — Basil merges.
- Branch already created: `feat/local-offgrid-storage`.

---

## File Structure

**Backend**
- `app/settings.py` — add `data_dir`, retention overrides, `api_cors_origins`.
- `app/api.py` *(new)* — FastAPI app: query helpers + REST + SSE.
- `app/events_bus.py` *(new)* — thin Redis pub/sub publish/subscribe for the `events:new` channel.
- `app/persistence.py` — publish a tick after a successful insert batch.
- `app/housekeeping.py` — env-overridable retention windows.
- `app/tasks.py` — refresh stale Supabase comment (no behaviour change).

**Frontend** (`osint-frontend/`)
- `lib/apiClient.ts` *(new)* — fetch wrapper + typed endpoint calls.
- `lib/queries.ts` — swap supabase-js calls for `apiClient`.
- `lib/realtime.ts` — swap supabase channel for `EventSource`.
- `app/providers.tsx` — swap `isSupabaseConfigured` for `isApiConfigured`.
- `lib/supabase.ts` — **delete**.
- `package.json` — drop `@supabase/supabase-js`.

**Infra / docs**
- `docker-compose.yml` — bind mounts + `api` service.
- `Makefile` *(new)* — `data-size`, `data-prune`, `data-reset`.
- `env.example` — drop `NEXT_PUBLIC_SUPABASE_*`; add `OSINT_DATA_DIR`, `NEXT_PUBLIC_API_URL`, retention vars.
- `supabase/` — **delete** directory.
- `README.md`, `MANUAL.md`, `docs/frontend/*` — describe local API + folder.

---

## Task 1: `OSINT_DATA_DIR` + retention settings

**Files:**
- Modify: `app/settings.py`
- Test: `tests/test_settings.py` *(new)*

**Interfaces:**
- Produces: `settings.data_dir: str`, `settings.retention_gdelt_days: int`, `settings.retention_news_days: int`, `settings.retention_hazard_days: int`, `settings.api_cors_origins: str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings.py
from app.settings import Settings


def test_data_dir_defaults_to_local_data():
    s = Settings(_env_file=None)
    assert s.data_dir == "./data"


def test_retention_overrides_from_env(monkeypatch):
    monkeypatch.setenv("RETENTION_GDELT_DAYS", "1")
    monkeypatch.setenv("RETENTION_NEWS_DAYS", "2")
    s = Settings(_env_file=None)
    assert s.retention_gdelt_days == 1
    assert s.retention_news_days == 2
    assert s.retention_hazard_days == 2  # default preserved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'data_dir'`

- [ ] **Step 3: Add the fields**

In `app/settings.py`, inside `class Settings`, after the `environment` field:

```python
    data_dir: str = Field(default="./data")

    retention_gdelt_days: int = Field(default=2)
    retention_news_days: int = Field(default=3)
    retention_hazard_days: int = Field(default=2)

    api_cors_origins: str = Field(default="http://localhost:3000")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/settings.py tests/test_settings.py
git commit -m "feat(settings): add OSINT_DATA_DIR + env-configurable retention windows"
```

---

## Task 2: Env-configurable retention in housekeeping

**Files:**
- Modify: `app/housekeeping.py:33-64` (the `RETENTION_DAYS` dict + module docstring/comments)
- Test: `tests/test_housekeeping.py` (extend)

**Interfaces:**
- Consumes: `settings.retention_gdelt_days`, `settings.retention_news_days`, `settings.retention_hazard_days`.
- Produces: `retention_days() -> dict[str, int | None]` (replaces the module-level constant).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_housekeeping.py — add
from app.housekeeping import retention_days


def test_retention_days_reads_settings(monkeypatch):
    monkeypatch.setattr("app.housekeeping.settings.retention_gdelt_days", 1)
    monkeypatch.setattr("app.housekeeping.settings.retention_news_days", 2)
    rd = retention_days()
    assert rd["gdelt"] == 1
    assert rd["rss-bbc-world"] == 2
    assert rd["fred"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_housekeeping.py::test_retention_days_reads_settings -v`
Expected: FAIL — `ImportError: cannot import name 'retention_days'`

- [ ] **Step 3: Replace the constant with a function**

In `app/housekeeping.py`, add the import and replace the `RETENTION_DAYS` dict (lines ~25-64) with a builder. Update the module docstring's "Supabase free-tier" wording to "local disk budget".

```python
from app.settings import settings


def retention_days() -> dict[str, int | None]:
    """Per-source retention windows (days). ``None`` = never delete.

    High-volume sources are pruned to a few days to keep the local disk
    budget small (GDELT is the largest table). News/hazard/GDELT windows are
    env-overridable via RETENTION_*_DAYS; market/macro history is irreplaceable
    so it is exempt.
    """
    news = settings.retention_news_days
    hazard = settings.retention_hazard_days
    return {
        "rss-bbc-world": news,
        "rss-bbc-uk": news,
        "rss-reuters-world": news,
        "rss-dawn": news,
        "rss-guardian-world": news,
        "rss-geo-english": news,
        "nasa-firms": hazard,
        "usgs-quake": hazard,
        "gdacs": hazard,
        "eonet": hazard,
        "gdelt": settings.retention_gdelt_days,
        "opensky-adsb": hazard,
        "abuse-ch-urlhaus": hazard,
        "abuse-ch-feodo": hazard,
        "polymarket": hazard,
        "uk-police": 7,
        "yfinance": 30,
        "fred": None,
    }
```

- [ ] **Step 4: Point `prune_events` at the function**

In `prune_events`, replace `for source, days in RETENTION_DAYS.items():` with:

```python
    policy = retention_days()
    for source, days in policy.items():
```

And replace the `explicit = set(RETENTION_DAYS)` line with `explicit = set(policy)`. The generic-RSS prune below it must use `days=settings.retention_news_days` instead of the literal `3`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_housekeeping.py -v`
Expected: PASS (existing tests + the new one)

- [ ] **Step 6: Commit**

```bash
git add app/housekeeping.py tests/test_housekeeping.py
git commit -m "feat(housekeeping): env-configurable retention windows, local-disk framing"
```

---

## Task 3: Redis events bus (publish/subscribe)

**Files:**
- Create: `app/events_bus.py`
- Test: `tests/test_events_bus.py` *(new)*

**Interfaces:**
- Produces:
  - `EVENTS_CHANNEL = "events:new"`
  - `publish_new_events(count: int, *, client: Redis | None = None) -> None` — publishes the string count; no-op when `count <= 0`.
  - `subscribe_new_events(client: Redis | None = None) -> Iterator[str]` — blocking generator yielding each message payload.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_events_bus.py
from unittest.mock import MagicMock

from app.events_bus import EVENTS_CHANNEL, publish_new_events


def test_publish_no_op_on_zero():
    client = MagicMock()
    publish_new_events(0, client=client)
    client.publish.assert_not_called()


def test_publish_sends_count():
    client = MagicMock()
    publish_new_events(7, client=client)
    client.publish.assert_called_once_with(EVENTS_CHANNEL, "7")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_events_bus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.events_bus'`

- [ ] **Step 3: Implement the bus**

```python
# app/events_bus.py
"""Lightweight Redis pub/sub used to wake SSE clients when new events land.

The payload is just the inserted-row count; subscribers re-query the DB for the
actual rows. Redis is already the Celery broker, so no new infrastructure.
"""
from __future__ import annotations

from collections.abc import Iterator

from redis import Redis

from app.settings import settings

EVENTS_CHANNEL = "events:new"

_client: Redis | None = None


def _default_client() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def publish_new_events(count: int, *, client: Redis | None = None) -> None:
    """Announce that ``count`` new events were inserted. No-op when count <= 0."""
    if count <= 0:
        return
    (client or _default_client()).publish(EVENTS_CHANNEL, str(count))


def subscribe_new_events(client: Redis | None = None) -> Iterator[str]:
    """Yield each message payload published to the events channel (blocking)."""
    pubsub = (client or _default_client()).pubsub()
    pubsub.subscribe(EVENTS_CHANNEL)
    try:
        for message in pubsub.listen():
            if message.get("type") == "message":
                yield message["data"]
    finally:
        pubsub.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_events_bus.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/events_bus.py tests/test_events_bus.py
git commit -m "feat(bus): Redis pub/sub channel for new-event notifications"
```

---

## Task 4: Publish tick from persistence

**Files:**
- Modify: `app/persistence.py:75-98` (`upsert_events`)
- Test: `tests/test_persistence.py` (extend)

**Interfaces:**
- Consumes: `publish_new_events` from Task 3.
- Behaviour: after all batches insert, publish the total inserted count. Publish failures must not break ingestion.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_persistence.py — add
from unittest.mock import patch

from app.models import Event  # adjust import to match existing test helpers


def test_upsert_publishes_inserted_count(db_session, make_event):
    # make_event: reuse the existing factory used by other persistence tests
    events = [make_event(source_event_id="a"), make_event(source_event_id="b")]
    with patch("app.persistence.publish_new_events") as pub:
        from app.persistence import upsert_events
        inserted = upsert_events(events, db_session)
    assert inserted == 2
    pub.assert_called_once_with(2)


def test_upsert_publish_failure_does_not_raise(db_session, make_event):
    with patch("app.persistence.publish_new_events", side_effect=RuntimeError("redis down")):
        from app.persistence import upsert_events
        inserted = upsert_events([make_event(source_event_id="x")], db_session)
    assert inserted == 1  # ingestion survives a dead Redis
```

> If `make_event` does not already exist in `tests/test_persistence.py`, reuse whatever construction the existing tests in that file use to build `Event` objects — match the established pattern rather than inventing a new factory.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_persistence.py -k publish -v`
Expected: FAIL — `publish_new_events` not imported / not called.

- [ ] **Step 3: Add the publish call**

In `app/persistence.py`, add the import near the top:

```python
from app.events_bus import publish_new_events
```

At the end of `upsert_events`, replace `return inserted` with:

```python
    try:
        publish_new_events(inserted)
    except Exception:
        # A dead Redis must never fail an ingest; the SSE clients fall back to
        # their 30s SWR poll. Swallow and continue.
        pass
    return inserted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_persistence.py -v`
Expected: PASS (existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add app/persistence.py tests/test_persistence.py
git commit -m "feat(persistence): publish new-event tick after successful upsert"
```

---

## Task 5: FastAPI read-API — REST endpoints

**Files:**
- Create: `app/api.py`
- Test: `tests/test_api.py` *(new)*

**Interfaces:**
- Produces FastAPI app `app` with:
  - `GET /health` → `{"status": "ok"}`
  - `GET /events?since=<iso>&sources=<csv>&exclude=<csv>&limit=<int>` → `list[EventOut]`, ordered `occurred_at` desc.
  - `GET /scores?limit=<int>` → `list[ScoreOut]`, ordered `bucket_start` desc.
- The DB session is provided by a `get_session` dependency, overridable in tests.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api.py
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api import app, get_session
from app.db_models import EventRow


def _seed(session):
    now = datetime.now(UTC)
    session.add_all([
        EventRow(source="gdelt", source_event_id="1", occurred_at=now,
                 category="conflict", keywords=[], payload={}),
        EventRow(source="opensky-adsb", source_event_id="2",
                 occurred_at=now - timedelta(hours=1),
                 category="aviation", keywords=[], payload={}),
    ])
    session.commit()


def _client(db_session):
    _seed(db_session)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_health():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}


def test_events_returns_rows(db_session):
    client = _client(db_session)
    rows = client.get("/events").json()
    assert {r["source"] for r in rows} == {"gdelt", "opensky-adsb"}
    app.dependency_overrides.clear()


def test_events_exclude_filter(db_session):
    client = _client(db_session)
    rows = client.get("/events?exclude=opensky-adsb").json()
    assert all(r["source"] != "opensky-adsb" for r in rows)
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api'`

- [ ] **Step 3: Implement the REST API**

```python
# app/api.py
"""Local read-API for the dashboard frontend. Replaces Supabase REST.

Read-only over the local Postgres. Serves recent events + latest scores, and
(see SSE task) a live stream. Run with: uvicorn app.api:app --port 8000
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.db_models import EventRow, ScoreRow
from app.settings import settings

app = FastAPI(title="OSINT local API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.api_cors_origins.split(",") if o.strip()],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def _event_dict(row: EventRow) -> dict:
    return {
        "id": str(row.id),
        "source": row.source,
        "source_event_id": row.source_event_id,
        "occurred_at": row.occurred_at.isoformat(),
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        "category": row.category,
        "severity": row.severity,
        "confidence": row.confidence,
        "keywords": list(row.keywords or []),
        "country": row.country,
        "lat": row.lat,
        "lon": row.lon,
        "payload": row.payload,
    }


def _score_dict(row: ScoreRow) -> dict:
    return {
        "country": row.country,
        "bucket_start": row.bucket_start.isoformat(),
        "score_name": row.score_name,
        "score_value": row.score_value,
        "components": row.components,
        "method_version": row.method_version,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/events")
def events(
    session: Session = Depends(get_session),
    since: datetime | None = Query(default=None),
    sources: str | None = Query(default=None),
    exclude: str | None = Query(default=None),
    limit: int = Query(default=5000, le=10000),
) -> list[dict]:
    stmt = select(EventRow).order_by(EventRow.occurred_at.desc()).limit(limit)
    if since is not None:
        stmt = stmt.where(EventRow.occurred_at >= since)
    if sources:
        stmt = stmt.where(EventRow.source.in_([s.strip() for s in sources.split(",")]))
    if exclude:
        stmt = stmt.where(EventRow.source.notin_([s.strip() for s in exclude.split(",")]))
    return [_event_dict(r) for r in session.execute(stmt).scalars()]


@app.get("/scores")
def scores(
    session: Session = Depends(get_session),
    limit: int = Query(default=5000, le=10000),
) -> list[dict]:
    stmt = select(ScoreRow).order_by(ScoreRow.bucket_start.desc()).limit(limit)
    return [_score_dict(r) for r in session.execute(stmt).scalars()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "feat(api): FastAPI read-API with /health, /events, /scores"
```

---

## Task 6: SSE `/stream` endpoint

**Files:**
- Modify: `app/api.py`
- Test: `tests/test_api.py` (extend)

**Interfaces:**
- Consumes: `subscribe_new_events` from Task 3.
- Produces: `GET /stream` → `text/event-stream`; emits `data: <count>\n\n` per Redis tick. Subscription generator is injected via `app.state.event_source` so tests can stub it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api.py — add
def test_stream_emits_ticks():
    from app.api import app
    app.state.event_source = lambda: iter(["3", "5"])
    client = TestClient(app)
    with client.stream("GET", "/stream") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = ""
        for chunk in resp.iter_text():
            body += chunk
            if "data: 5" in body:
                break
    assert "data: 3" in body and "data: 5" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_api.py::test_stream_emits_ticks -v`
Expected: FAIL — 404 (no `/stream` route)

- [ ] **Step 3: Add the SSE endpoint**

In `app/api.py` add the import:

```python
from fastapi.responses import StreamingResponse

from app.events_bus import subscribe_new_events
```

Set the default source after `app = FastAPI(...)`:

```python
app.state.event_source = subscribe_new_events
```

Add the route:

```python
@app.get("/stream")
def stream() -> StreamingResponse:
    source = app.state.event_source

    def gen():
        yield ": connected\n\n"  # prelude so EventSource fires onopen
        for count in source():
            yield f"data: {count}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: PASS (all api tests)

- [ ] **Step 5: Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "feat(api): SSE /stream forwarding Redis new-event ticks"
```

---

## Task 7: Frontend API client

**Files:**
- Create: `osint-frontend/lib/apiClient.ts`
- Test: `osint-frontend/lib/apiClient.test.mts` *(new — matches existing `.test.mts` convention)*

**Interfaces:**
- Produces:
  - `API_BASE: string` — `process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"`.
  - `isApiConfigured: boolean` — always `true` (default base is valid).
  - `fetchEvents(params?: { since?: string; sources?: string[]; exclude?: string[]; limit?: number }): Promise<EventRow[]>`
  - `fetchScores(limit?: number): Promise<ScoreRow[]>`
  - `streamUrl(): string` — `${API_BASE}/stream`.

- [ ] **Step 1: Write the failing test**

```typescript
// osint-frontend/lib/apiClient.test.mts
import { describe, it, expect, vi, afterEach } from "vitest"
import { fetchEvents, streamUrl } from "./apiClient"

afterEach(() => vi.restoreAllMocks())

describe("apiClient", () => {
  it("builds the events query string", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    )
    await fetchEvents({ exclude: ["opensky-adsb"], limit: 100 })
    const url = (spy.mock.calls[0][0] as string)
    expect(url).toContain("/events?")
    expect(url).toContain("exclude=opensky-adsb")
    expect(url).toContain("limit=100")
  })

  it("exposes the stream url", () => {
    expect(streamUrl()).toMatch(/\/stream$/)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd osint-frontend && pnpm vitest run lib/apiClient.test.mts`
Expected: FAIL — cannot resolve `./apiClient`

- [ ] **Step 3: Implement the client**

```typescript
// osint-frontend/lib/apiClient.ts
import type { EventRow, ScoreRow } from "./types"

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

// Local API always has a valid default base; kept as a named export so call
// sites read the same way the old isSupabaseConfigured did.
export const isApiConfigured = true

export interface EventQuery {
  since?: string
  sources?: string[]
  exclude?: string[]
  limit?: number
}

export async function fetchEvents(params: EventQuery = {}): Promise<EventRow[]> {
  const qs = new URLSearchParams()
  if (params.since) qs.set("since", params.since)
  if (params.sources?.length) qs.set("sources", params.sources.join(","))
  if (params.exclude?.length) qs.set("exclude", params.exclude.join(","))
  if (params.limit != null) qs.set("limit", String(params.limit))
  const res = await fetch(`${API_BASE}/events?${qs.toString()}`)
  if (!res.ok) throw new Error(`GET /events ${res.status}`)
  return (await res.json()) as EventRow[]
}

export async function fetchScores(limit = 5000): Promise<ScoreRow[]> {
  const res = await fetch(`${API_BASE}/scores?limit=${limit}`)
  if (!res.ok) throw new Error(`GET /scores ${res.status}`)
  return (await res.json()) as ScoreRow[]
}

export function streamUrl(): string {
  return `${API_BASE}/stream`
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd osint-frontend && pnpm vitest run lib/apiClient.test.mts`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add osint-frontend/lib/apiClient.ts osint-frontend/lib/apiClient.test.mts
git commit -m "feat(frontend): local API client (events/scores/stream)"
```

---

## Task 8: Rewrite queries.ts onto the API client

**Files:**
- Modify: `osint-frontend/lib/queries.ts` (`fetchScores` at :100-110, `useCountryEvents` at :148+, and any other `getSupabase()` call in the file)

**Interfaces:**
- Consumes: `fetchScores`, `fetchEvents` from Task 7.
- The exported hooks (`useEventsInWindow`, `useLatestScores`, `useCountryEvents`) keep their existing signatures and return shapes — only the data source changes.

- [ ] **Step 1: Replace the scores fetcher**

Remove `import { getSupabase } from "./supabase"`. Add `import { fetchEvents, fetchScores as apiFetchScores } from "./apiClient"`.

Replace the local `fetchScores` (lines ~100-110) with:

```typescript
async function fetchScores(): Promise<ScoreRow[]> {
  return apiFetchScores(5000)
}
```

- [ ] **Step 2: Replace the country-events fetcher**

In `useCountryEvents`, replace the supabase block with:

```typescript
    async () => {
      if (!country) return []
      return fetchEvents({ sources: undefined, limit: 200 }).then((rows) =>
        rows.filter((r) => r.country === country),
      )
    },
```

> If the API should filter by country server-side instead, add a `country` query param to `/events` in Task 5 and pass it here. For the first cut, client-side filter on a 200-row page is acceptable and keeps the API surface minimal (YAGNI).

- [ ] **Step 3: Grep for stragglers**

Run: `cd osint-frontend && grep -n "getSupabase\|supabase" lib/queries.ts`
Expected: no matches.

- [ ] **Step 4: Typecheck**

Run: `cd osint-frontend && pnpm exec tsc --noEmit`
Expected: no errors from `queries.ts`.

- [ ] **Step 5: Commit**

```bash
git add osint-frontend/lib/queries.ts
git commit -m "refactor(frontend): queries.ts reads from local API not Supabase"
```

---

## Task 9: Rewrite realtime.ts onto SSE

**Files:**
- Modify: `osint-frontend/lib/realtime.ts`

**Interfaces:**
- Consumes: `fetchEvents`, `streamUrl` from Task 7.
- Produces: `EventBuffer` with the same public surface (`ingest`, `getSnapshot`, `getStatus`, `getDiagnostics`, `subscribe`, `subscribeStatus`, `connect`, `disconnect`) so `providers.tsx` and consumers are unchanged.

The new transport is an `EventSource`. On each SSE message, backfill recent events via REST (reuses the existing ring-buffer + dedupe). The reconnect/poll/heartbeat machinery simplifies because `EventSource` auto-reconnects.

- [ ] **Step 1: Replace imports + transport**

At the top, replace the supabase imports with:

```typescript
import { fetchEvents, streamUrl } from "./apiClient"
import { sourceKeyForEvent, type EventRow } from "./types"
```

Replace the `private channel: RealtimeChannel | null = null` field with:

```typescript
  private source: EventSource | null = null
```

- [ ] **Step 2: Replace `connect()`**

```typescript
  /** Open the SSE stream. EventSource auto-reconnects, so no manual backoff. */
  connect(): void {
    this.stopped = false
    if (this.source) return
    this.setStatus("connecting")
    const es = new EventSource(streamUrl())
    this.source = es
    es.onopen = () => {
      this.lastSeenAt = new Date()
      this.setStatus("connected")
      this.reconnectAttempts = 0
      this.stopPolling()
      void this.backfillSinceLastSeen()
    }
    es.onmessage = () => {
      this.lastSeenAt = new Date()
      void this.backfillSinceLastSeen()
    }
    es.onerror = () => {
      // EventSource retries on its own; surface the state + arm the poll
      // fallback so data still flows if the stream stays down.
      this.setStatus(this.reconnectAttempts >= MAX_RECONNECT_BEFORE_POLL ? "polling" : "reconnecting")
      this.reconnectAttempts += 1
      if (this.reconnectAttempts >= MAX_RECONNECT_BEFORE_POLL) this.startPolling()
    }
  }
```

- [ ] **Step 3: Replace `backfillSinceLastSeen()`**

```typescript
  private async backfillSinceLastSeen(): Promise<void> {
    const since = this.lastEventAt
      ? this.lastEventAt.toISOString()
      : new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
    try {
      const rows = await fetchEvents({ since, exclude: ["opensky-adsb"], limit: 500 })
      if (rows.length) this.ingest(rows)
    } catch {
      // Network blip; next SSE message or poll tick retries.
    }
  }
```

- [ ] **Step 4: Replace `disconnect()` and delete supabase-only methods**

Replace `disconnect()` body's supabase teardown with:

```typescript
  disconnect(): void {
    this.stopped = true
    this.stopHeartbeat()
    this.stopPolling()
    if (this.source) {
      this.source.close()
      this.source = null
    }
    this.setStatus("disconnected")
  }
```

Delete the now-unused `scheduleReconnect()`, `startHeartbeat()`, `stopHeartbeat()`, `pingHeartbeat()`, `reconnectTimer`, `heartbeatTimer`, and `reconnecting` members **only if** no longer referenced. `startPolling`/`stopPolling`/`pollTimer` stay (used by the error fallback). Keep `BACKOFF_SCHEDULE_MS`/`backoffMs` only if still referenced; otherwise delete.

- [ ] **Step 5: Typecheck**

Run: `cd osint-frontend && pnpm exec tsc --noEmit`
Expected: no errors; no references to `RealtimeChannel` or `getSupabase`.

- [ ] **Step 6: Commit**

```bash
git add osint-frontend/lib/realtime.ts
git commit -m "refactor(frontend): realtime.ts uses SSE EventSource not Supabase channels"
```

---

## Task 10: Providers + delete supabase.ts + drop dependency

**Files:**
- Modify: `osint-frontend/app/providers.tsx`
- Delete: `osint-frontend/lib/supabase.ts`
- Modify: `osint-frontend/package.json`
- Modify: any remaining importer (e.g. `components/DashboardSection.tsx`)

**Interfaces:**
- Consumes: `isApiConfigured`, `fetchEvents` from Task 7.

- [ ] **Step 1: Swap providers data source**

In `app/providers.tsx`: replace `import { getSupabase, isSupabaseConfigured } from "@/lib/supabase"` with `import { fetchEvents, isApiConfigured } from "@/lib/apiClient"`.

Replace `fetchRecentEvents` body with:

```typescript
async function fetchRecentEvents(): Promise<EventRow[]> {
  const since = new Date(Date.now() - WINDOW_MS).toISOString()
  return fetchEvents({ since, exclude: ["opensky-adsb"], limit: TARGET_ROWS })
}
```

Replace every `isSupabaseConfigured` with `isApiConfigured` (3 occurrences: the `useEffect` guard, the SWR key, and the `configured` value).

- [ ] **Step 2: Find and fix other importers**

Run: `cd osint-frontend && grep -rn "lib/supabase\|isSupabaseConfigured\|getSupabase\|@supabase/supabase-js" --include="*.ts" --include="*.tsx" .`
For each hit, replace with the `apiClient` equivalent (`isApiConfigured` / `fetchEvents` / `fetchScores`). The `realtime.ts`/`queries.ts`/`providers.tsx` hits are already handled by earlier tasks.

- [ ] **Step 3: Delete the supabase module + dependency**

```bash
cd osint-frontend
rm lib/supabase.ts
pnpm remove @supabase/supabase-js
```

- [ ] **Step 4: Typecheck + lint + tests**

Run:
```bash
cd osint-frontend && pnpm exec tsc --noEmit && pnpm vitest run
```
Expected: no type errors; vitest green; no remaining `@supabase/supabase-js` import.

- [ ] **Step 5: Commit**

```bash
git add osint-frontend
git commit -m "refactor(frontend): drop Supabase — providers + remove supabase-js dep"
```

---

## Task 11: docker-compose bind mounts + api service

**Files:**
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `OSINT_DATA_DIR` env (default `./data`).

- [ ] **Step 1: Replace named volumes with bind mounts**

In `docker-compose.yml`, change the postgres volume to:

```yaml
    volumes:
      - ${OSINT_DATA_DIR:-./data}/postgres:/var/lib/postgresql/data
```

The redis volume to:

```yaml
    volumes:
      - ${OSINT_DATA_DIR:-./data}/redis:/data
```

Delete the top-level `volumes:` block (`postgres_data`, `redis_data`) — no longer used.

- [ ] **Step 2: Add the api service**

```yaml
  api:
    build: .
    restart: unless-stopped
    command: uvicorn app.api:app --host 0.0.0.0 --port 8000
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    ports:
      - "8000:8000"
```

> If the repo has no `Dockerfile`, run the API as a host process instead (document `uvicorn app.api:app --port 8000` in MANUAL.md) and skip the `api` service. Check with `ls Dockerfile`.

- [ ] **Step 3: Validate compose config**

Run: `OSINT_DATA_DIR=./data docker compose config >/dev/null && echo OK`
Expected: `OK` (no schema errors).

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(infra): bind-mount data into OSINT_DATA_DIR + api service"
```

---

## Task 12: Makefile data-management targets

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Write the Makefile**

```makefile
# Local data management. OSINT_DATA_DIR defaults to ./data (see .env).
OSINT_DATA_DIR ?= ./data

.PHONY: data-size data-prune data-reset

data-size:  ## Show disk used by each data subfolder
	@du -sh $(OSINT_DATA_DIR)/* 2>/dev/null || echo "no data yet at $(OSINT_DATA_DIR)"

data-prune:  ## Run retention housekeeping now
	.venv/bin/python -c "from app.db import session_scope; from app.housekeeping import prune_events; \
	import json; \
	[print(json.dumps(prune_events(s))) for s in [next(iter([__import__('app.db', fromlist=['session_scope']).session_scope().__enter__()]))]]"

data-reset:  ## Stop stack and wipe all local data (DESTRUCTIVE)
	docker compose down
	rm -rf $(OSINT_DATA_DIR)
	@echo "wiped $(OSINT_DATA_DIR)"
```

> `data-prune`'s one-liner is awkward; prefer a tiny script. Replace the recipe body with `.venv/bin/python scripts/prune_now.py` and create `scripts/prune_now.py`:
> ```python
> from app.db import session_scope
> from app.housekeeping import prune_events
> import json
> with session_scope() as s:
>     print(json.dumps(prune_events(s)))
> ```

- [ ] **Step 2: Verify targets parse**

Run: `make -n data-size data-reset`
Expected: prints the commands without executing.

- [ ] **Step 3: Smoke-test size target**

Run: `make data-size`
Expected: either sizes or "no data yet" — no error.

- [ ] **Step 4: Commit**

```bash
git add Makefile scripts/prune_now.py
git commit -m "feat(make): data-size / data-prune / data-reset targets"
```

---

## Task 13: env.example, delete supabase/, docs

**Files:**
- Modify: `env.example`
- Delete: `supabase/` directory
- Modify: `README.md`, `MANUAL.md`, `docs/frontend/README.md`

- [ ] **Step 1: Update env.example**

Remove the two `NEXT_PUBLIC_SUPABASE_*` lines and the Supabase paragraph in the Postgres comment. Add under an `# App` / new `# Local storage` section:

```bash
# Local storage — all DB/redis/archive data lives here (one folder).
# Laptop: leave default. Pi/external HDD: set an absolute path.
OSINT_DATA_DIR=./data

# Retention windows (days). Defaults keep only the latest few days.
RETENTION_GDELT_DAYS=2
RETENTION_NEWS_DAYS=3
RETENTION_HAZARD_DAYS=2

# Frontend → local API (replaces Supabase REST/realtime)
NEXT_PUBLIC_API_URL=http://localhost:8000
```

- [ ] **Step 2: Delete the supabase directory**

```bash
git rm -r supabase
```

- [ ] **Step 3: Update docs**

In `README.md` and `MANUAL.md`: replace Supabase setup/usage with: start stack (`docker compose up -d`), run API (`uvicorn app.api:app --port 8000`), frontend reads `NEXT_PUBLIC_API_URL`, data lives in `OSINT_DATA_DIR`, manage with `make data-size|data-prune|data-reset`. In `docs/frontend/README.md` replace the Supabase env/section with the `NEXT_PUBLIC_API_URL` model.

Run: `grep -rln "supabase" README.md MANUAL.md docs/ env.example`
Expected: no matches (or only historical changelog mentions — leave those).

- [ ] **Step 4: Commit**

```bash
git add env.example README.md MANUAL.md docs/
git commit -m "docs: de-Supabase env + setup; document local API + data folder"
```

---

## Task 14: Full verification + PR

- [ ] **Step 1: Backend suite**

Run: `.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 2: Frontend suite + typecheck + lint**

Run: `cd osint-frontend && pnpm vitest run && pnpm exec tsc --noEmit && pnpm lint`
Expected: all green.

- [ ] **Step 3: No Supabase references remain**

Run: `grep -rln "supabase" --include="*.ts" --include="*.tsx" --include="*.py" --include="*.yml" --include="*.json" . | grep -v node_modules | grep -v package-lock`
Expected: no matches.

- [ ] **Step 4: Manual smoke (optional, needs docker)**

Bring up stack, run a fetch, confirm `make data-size` shows `postgres/`, dashboard renders from `http://localhost:8000`, `make data-reset` clears the folder.

- [ ] **Step 5: Push + open PR (do NOT merge)**

```bash
git push -u origin feat/local-offgrid-storage
gh pr create --title "Go fully local + off-grid: remove Supabase, one-folder storage, configurable retention" \
  --body "Closes #201. See docs/superpowers/specs/2026-06-25-local-offgrid-storage-design.md"
```

---

## Self-Review

- **Spec coverage:** A (storage) → Tasks 1,11,12,13. B (read-API) → Tasks 5,6 (+3,4 for realtime emit). C (frontend) → Tasks 7,8,9,10. D (retention) → Tasks 1,2. E (mgmt/cleanup) → Tasks 12,13. All covered.
- **Placeholders:** none — every code step has concrete code. `data-prune` one-liner flagged with a clean script alternative.
- **Type consistency:** `publish_new_events(count)` (Task 3) called in Task 4; `fetchEvents`/`fetchScores`/`streamUrl` (Task 7) consumed in 8/9/10; `isApiConfigured` replaces `isSupabaseConfigured` everywhere; `EventBuffer` public surface preserved so `providers.tsx` is untouched beyond data source.
- **Open risk noted in spec:** SSE emit point resolved (Task 4 publishes one tick per batch, not per row).
