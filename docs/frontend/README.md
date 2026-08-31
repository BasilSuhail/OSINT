# Frontend setup

The dashboard is a Next.js App Router application. It reads from the local
FastAPI read API (`app/api.py`) through a same-origin `/api` route — no managed
cloud service required.

## Architecture

```
Browser
   │
   ├── fetch(/api/*)  ─→  Next/TLS proxy  ─→  FastAPI  ─→  Postgres
   │      /events  /scores  /ingest-health  /stream (SSE)
   │
   └── react-map-gl + MapLibre GL  → renders world map + markers
```

Two primary API endpoints consumed by the dashboard:

- `GET /events` — raw OSINT events (lat / lon / severity / category / payload).
  Besides recent/revision filters, it accepts a complete `west`/`south`/`east`/`north`
  bbox, `since`/`until`, `positioned_only`, and the lossless
  `occurred_before`/`occurred_before_id` cursor pair.
- `GET /scores` — composite stress per (country, month)

Additional endpoints: `GET /health`, `GET /ingest-health`, `GET /stream` (SSE for live pushes).

The world view deliberately uses a bounded recent-event buffer. At city/street
zoom (8+), the map separately pages every positioned row inside the visible bbox
and selected time window, merges those rows by event ID, then applies the same
filters, exact-coordinate projection, provenance UI, and MapLibre clustering.
This keeps the global view bounded without allowing its row cap to erase local
events. Each settled map move or time-window change replaces the prior local
snapshot. A failed refresh is shown explicitly and labels the retained rows as
the last complete snapshot; it never presents stale rows as current. Historical
playback appends only the newly entered time slice
every two seconds and pages revisions since the prior snapshot, avoiding
repeated full-window reads without losing late-ingested or backfilled rows.

Map clicks are local selections, not implicit country selections. Event dots
and clusters keep first priority. Any other click resolves the most specific
rendered building, street, neighbourhood, town, or city label; unlabeled ground
uses its coordinates. The selection card lists deduplicated positioned events
inside a visible zoom-scaled boundary, grouped by day and nearest-first within
each day, then refreshes when the complete selected-area snapshot arrives.
Country aggregation remains available only through explicit country navigation
such as the world list or future search.
Selection never moves or zooms the map. Cluster and local-area cards follow the
situation feed's timeline hierarchy: calendar sections, absolute times, numbered
multi-line rows, category chips, and source/location/distance context.

## Phase 1 — pages

| Page | What it shows | Data |
|---|---|---|
| `/` | World map: country choropleth from latest composite score, point markers for recent hazard events | `/scores`, `/events?category=hazard` |
| `/articles` | Card list of recent geopolitical events with source URL | `/events?category=geopolitical` |

## Phase 2 — pages (later)

| Page | What it shows | Data |
|---|---|---|

## Versions

- `v0-prompt.md` — original spec: dual-pane map + globe, filters, time scrubber, live fades. Dark, dense, analytical. The globe half was removed in #494; the map is now the only geographic surface.
- `v0-prompt-v1-simple.md` — archived first draft: single-page world map + articles, no globe.

## Setup

### 1. Bring up the local stack

```bash
cp env.example .env        # fill POSTGRES_PASSWORD + API keys
docker compose up -d       # starts Postgres + Redis + Celery workers
```

### 2. Start the API host process

Run this as a separate terminal session (or systemd unit on the Pi):

```bash
.venv/bin/uvicorn app.api:app --host 0.0.0.0 --port 8000
```

The API has no Dockerfile — it runs directly on the host Python environment.

### 3. Set the frontend env var

In the frontend repo's `.env.local`:

```bash
NEXT_PUBLIC_API_URL=/api
```

`next.config.mjs` proxies `/api/*` to the local API for development and LAN
sharing. Keeping the browser URL relative also prevents mixed-content failures
when an HTTPS edge terminates TLS in front of the two local services.

When Next is hosted separately from the API, set its server-side upstream too:

```bash
NEXT_PUBLIC_API_URL=/api
API_PROXY_TARGET=https://api.example.invalid
```

The browser still calls its own HTTPS origin; only the hosted Next server uses
the upstream URL.

### 4. Start the frontend

```bash
cd osint-frontend
pnpm install
pnpm dev        # or: pnpm build && pnpm start
```

### 5. Done

The dashboard reads live data from the local API, refreshes via SSE (`/stream`) and periodic polling, shows country shading by composite score, hazard markers, a recent-events feed, and a fixed top status strip with realtime/API/source-health indicators.

## Installable apps

The console at `/` and the reading view at `/news` are separate standalone web
apps. Each route publishes its own manifest, installed identity, start URL,
Apple title, and icon set. No service worker is required because installation,
not offline operation, is the goal.

An HTTPS reverse proxy must route the frontend at `/` and strip `/api` before
forwarding API requests. One private-network configuration is:

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:3000
sudo tailscale serve --bg --https=443 --set-path=/api http://127.0.0.1:8000
```

Both pages can then be installed independently from the browser's Add to Home
Screen or Install action.

### App icons

The editable sources live in `osint-frontend/icons-src/`. Regenerate the
committed PNGs after changing them:

```bash
cd osint-frontend
mkdir -p public/app-icons
rsvg-convert -w 180 -h 180 icons-src/osint.svg -o public/app-icons/osint-apple-touch.png
rsvg-convert -w 192 -h 192 icons-src/osint.svg -o public/app-icons/osint-192.png
rsvg-convert -w 512 -h 512 icons-src/osint.svg -o public/app-icons/osint-512.png
rsvg-convert -w 512 -h 512 icons-src/osint-maskable.svg -o public/app-icons/osint-maskable-512.png
rsvg-convert -w 180 -h 180 icons-src/news.svg -o public/app-icons/news-apple-touch.png
rsvg-convert -w 192 -h 192 icons-src/news.svg -o public/app-icons/news-192.png
rsvg-convert -w 512 -h 512 icons-src/news.svg -o public/app-icons/news-512.png
rsvg-convert -w 512 -h 512 icons-src/news-maskable.svg -o public/app-icons/news-maskable-512.png
```

Apple icons use square, full-bleed artwork because the operating system applies
its own rounded mask. The maskable variants draw the mark smaller so circular
Android crops keep the whole symbol.

## Data management

```bash
make data-size    # show disk usage under OSINT_DATA_DIR
make data-prune   # trim rows older than RETENTION_* thresholds
make data-reset   # wipe everything (destructive — dev only)
```

## Iteration

The v0 prompt files are starting points. Re-open the v0 chat and tweak (colors, filters, etc.). v0 regenerates. The API contract (endpoint shapes) in `app/api.py` is the source of truth for what the frontend can read.
