# Design: Supabase → fully-local, off-grid storage

**Date:** 2026-06-25
**Branch:** `feat/local-offgrid-storage`
**Status:** Approved (brainstorming) — pending implementation plan

## Problem

The stack currently can be pointed at managed Supabase Postgres, and the
Next.js frontend reads data **exclusively** through Supabase (`@supabase/supabase-js`
REST + realtime channels). Supabase is eating disk/quota and slowing the
pipeline. Goal: run everything **locally and off-grid**, with all persistent
data consolidated in **one configurable folder** that is trivial to locate,
size, prune, and delete. Keep only the latest news (1–3 day retention windows,
GDELT especially since it is the largest table).

## Goals

- Zero dependency on Supabase (or any managed cloud DB) at runtime.
- All persistent state (Postgres data, Redis data, future archives) under a
  single `OSINT_DATA_DIR` folder.
- Frontend gets data from a **local backend HTTP API**, not Supabase.
- Aggressive, env-configurable retention; GDELT and news pruned to ≤3 days.
- Simple commands to track size / prune / wipe local data.

## Non-goals

- Authentication / RLS (was Supabase RLS; off-grid single-user → not needed).
- Parquet cold-archival (folder reserved, implementation deferred — YAGNI now).
- Any change to the ingestion fetchers or scoring logic.

## Current state (verified)

- `docker-compose.yml` already runs local `postgres:16-alpine` + `redis:7-alpine`,
  but via **Docker named volumes** (`postgres_data`, `redis_data`) → data hidden
  in Docker's area, not one tidy folder.
- Backend persists via SQLAlchemy to `settings.postgres_url` (defaults to
  `localhost`). Supabase was only ever an alternate `POSTGRES_HOST`.
- `app/housekeeping.py` already prunes per-source: GDELT=2d, news (rss-*)=3d,
  hazard=2d, market/macro=30d/None. Beat task `app.tasks.run_housekeeping`
  runs **daily 03:00 UTC**.
- Backend exposes **no HTTP API**. Frontend (`osint-frontend/lib/`) reads via
  `supabase.ts` + `queries.ts` (REST) + `realtime.ts` (supabase channels).
- `fastapi`, `uvicorn[standard]`, `redis`, `sqlalchemy` already in
  `requirements.txt` / `pyproject.toml` — no new backend deps.
- `data/` is already gitignored.

## Design

### A. Storage consolidation (one folder)

- Add `OSINT_DATA_DIR` env var, default `./data` (already gitignored). Any
  external path works (Pi + external HDD: `OSINT_DATA_DIR=/mnt/hdd/osint-data`).
- `docker-compose.yml`: replace named volumes with bind mounts:
  - `${OSINT_DATA_DIR:-./data}/postgres` → Postgres `/var/lib/postgresql/data`
  - `${OSINT_DATA_DIR:-./data}/redis` → Redis `/data`
  - `${OSINT_DATA_DIR:-./data}/archives` reserved for future parquet.
- Rationale: laptop dev = zero-config default; Pi/HDD = one env line. Repo
  stays small; data never on the SD card / system disk.

### B. Backend read-API (replaces Supabase REST + realtime)

New `app/api.py` — FastAPI app reading local Postgres through the existing
SQLAlchemy session factory (`app.db.session_scope`). Endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | liveness |
| GET | `/events?since=&sources=&limit=` | recent events (mirrors current frontend query) |
| GET | `/scores` | latest CII / composite scores |
| GET | `/stream` | **SSE** — pushes new events live |

- Run as one process: `uvicorn app.api:app --host 0.0.0.0 --port 8000`.
  Added to `docker-compose.yml` (or documented as a host process) + `MANUAL.md`.
- CORS: allow the frontend origin (localhost dev).
- **Realtime mechanism:** persistence publishes new-event IDs to a Redis
  pub/sub channel on insert; `/stream` subscribes and emits SSE. Redis is
  already the Celery broker, so no new infra. (Plan step: confirm the cheapest
  emit point in `app/persistence.py`.)

### C. Frontend de-Supabase

- Delete `osint-frontend/lib/supabase.ts`.
- Add `osint-frontend/lib/apiClient.ts` — fetch wrapper, base URL from
  `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).
- Rewrite `lib/queries.ts` → fetch the REST endpoints (keep SWR + zustand and
  the existing windowing/filter logic; only the data source changes).
- Rewrite `lib/realtime.ts` → `EventSource('/stream')` instead of supabase
  channel subscriptions.
- Remove `@supabase/supabase-js` from `osint-frontend/package.json`.
- Update `osint-frontend/app/providers.tsx` + `components/DashboardSection.tsx`
  references.

### D. Retention (mostly done — tighten + make configurable)

- `app/housekeeping.py`: lift hardcoded windows to env overrides with current
  defaults preserved (e.g. `RETENTION_GDELT_DAYS=2`, `RETENTION_NEWS_DAYS=3`,
  `RETENTION_HAZARD_DAYS=2`). Defaults unchanged if env unset.
- Replace stale "Supabase free tier" comments with "local disk budget" framing.
- No schedule change — daily 03:00 UTC prune is adequate for ≤3d windows.

### E. Management + cleanup

- `Makefile` targets:
  - `data-size` → `du -sh "$OSINT_DATA_DIR"/*`
  - `data-prune` → run housekeeping now (one-off celery/python invocation)
  - `data-reset` → `docker compose down` + `rm -rf "$OSINT_DATA_DIR"`
- Delete `supabase/` directory (RLS SQL + README — no longer used).
- `env.example`: remove `NEXT_PUBLIC_SUPABASE_*`; add `OSINT_DATA_DIR` and
  `NEXT_PUBLIC_API_URL`.
- Update `README.md`, `MANUAL.md`, `docs/frontend/*` to describe the local API
  + data folder instead of Supabase.

## Data flow (after)

```
fetchers → Celery tasks → SQLAlchemy → local Postgres (OSINT_DATA_DIR/postgres)
                                  └→ Redis pub/sub (new-event IDs)
local Postgres ← app/api.py (FastAPI) → REST  → frontend queries.ts (SWR)
Redis channel  → app/api.py /stream (SSE) → frontend realtime.ts (EventSource)
housekeeping (daily 03:00 UTC) → prune per-source ≤3d
```

## Testing

- Backend: unit tests for `/events`/`/scores` query builders against the
  existing test Postgres fixture (vitest is frontend; pytest for backend).
- Retention: extend existing housekeeping tests to cover env-override parsing.
- Frontend: existing vitest helper tests stay green; mock `apiClient` for
  query/realtime units.
- Manual: `make data-size` after a run shows the folder; `make data-reset`
  clears it; dashboard renders from the local API with Supabase uninstalled.

## Risks / open questions

- **SSE emit point:** need a cheap hook in persistence to publish new-event IDs.
  If persistence is bulk-insert heavy, publish a single "tick" per batch rather
  than per row. Resolve during planning.
- **Frontend query parity:** `queries.ts` currently relies on supabase-js
  filtering server-side; the REST API must reproduce the same filters
  (sources, since, limit) to avoid over-fetching.

## Rollback

Supabase path is removed, not toggled. Rollback = git revert the branch; the
old `POSTGRES_HOST=db.xxx.supabase.co` config still works against the
unchanged SQLAlchemy layer if ever needed (backend was never Supabase-specific).
