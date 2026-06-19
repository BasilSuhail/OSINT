# v0.dev prompt — OSINT dashboard (v1, simple)

Archived first draft of the v0 prompt. Kept as a fallback in case the dual-pane v2 in `v0-prompt.md` is too ambitious for v0 to generate cleanly in one shot.

Copy the section below verbatim into [v0.dev](https://v0.dev).

---

Build a Next.js 15 dashboard called "OSINT World Monitor" that reads data from a Supabase Postgres and renders a world map plus a list of recent news-style events. Two pages, dark theme, clean and analytical (think Bloomberg Terminal meets MapTiler). Refresh every 60 seconds.

## Stack

- Next.js 15 App Router, TypeScript
- Tailwind CSS
- shadcn/ui for components
- `@supabase/supabase-js` for data
- `react-map-gl` (MapLibre flavour, no Mapbox token needed) for the world map
- `swr` for periodic refresh
- `date-fns` for time formatting

## Environment

Two public env vars only:

```
NEXT_PUBLIC_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=eyJ...
```

Create a `lib/supabase.ts` that initialises the client once. Never read these in components directly.

## Database schema (already exists, read-only from frontend)

Two tables are publicly readable via RLS:

**events**
- `id` bigint
- `source` text — e.g. `gdelt`, `yfinance`, `usgs-quake`, `gdacs`, `nasa-firms`
- `source_event_id` text
- `occurred_at` timestamptz
- `category` text — one of `market`, `geopolitical`, `hazard`
- `severity` real — 0..1
- `keywords` text[]
- `country` char(2) — ISO 3166-1 alpha-2
- `lat` double precision
- `lon` double precision
- `payload` jsonb — raw source record; for GDELT contains `source_url`; for USGS contains `place`, `magnitude`

**scores**
- `country` char(2)
- `bucket_start` timestamptz
- `score_name` text — usually `composite`
- `score_value` real — 0..1
- `components` jsonb — `{ "z": { "market": …, "geopolitical": …, "hazard": … }, "contribution": {…} }`
- `method_version` text — `v1.0`

## Page 1 — `/` World map

Full-screen world map. Background dark gray. Use `react-map-gl/maplibre` with the OpenFreeMap dark tile style `https://tiles.openfreemap.org/styles/dark`.

### Country shading

For each country, fetch the latest `score_value` from `scores` (`order by computed_at desc limit 1` per country). Render a light fill over each country shaped by score:

- 0.0 → 0.4 = green tint (calm) — `rgba(34, 197, 94, 0.15)`
- 0.4 → 0.6 = yellow tint (watch) — `rgba(234, 179, 8, 0.20)`
- 0.6 → 0.8 = orange tint (warning) — `rgba(249, 115, 22, 0.25)`
- 0.8 → 1.0 = red tint (stress) — `rgba(239, 68, 68, 0.30)`

Use a world countries GeoJSON from a public source (e.g. `https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson`). Join on ISO alpha-2 country code.

### Event markers

Overlay point markers from `events` where `lat` is not null and `occurred_at` within the last 7 days. Marker style varies by source:

- `usgs-quake` → solid red circle, radius = `payload.magnitude * 2` clamped 4..16
- `gdacs` → orange diamond, larger
- `nasa-firms` → small yellow dot
- `gdelt` (only if lat exists) → small grey circle

Cluster automatically at low zoom levels.

### Side panel

When a country is clicked, slide a right panel showing:

- Country name + ISO code
- Latest composite score (big numeric)
- Per-domain breakdown bars (market / geopolitical / hazard) from `components.z`
- Last 10 events in that country, with category icon, time ago, source, severity
- Link to `/articles?country=XX` for full list

### Top bar

Logo "OSINT World Monitor" left. Right: last refresh time. Auto-refresh every 60s.

## Page 2 — `/articles`

Card list of recent geopolitical events. Each card:

- Country flag + ISO code
- Time ago (e.g. "2 hours ago")
- Severity badge (color from the scale above)
- Keywords as small pill chips
- Source domain extracted from `payload.source_url`
- Click → open the source URL in a new tab

Filters at top:

- Country (multi-select from distinct `events.country`)
- Severity threshold (slider 0..1)
- Time window (last 24h / 7d / 30d)

Pagination: 50 cards per page.

## Data queries

Build a `useEvents()` SWR hook hitting the Supabase client with proper filters. Build a `useLatestScores()` hook returning one row per country (latest by `computed_at`).

Do **not** select the `payload` column on list views — only fetch it when the side panel opens (separate query by event id).

## Visual rules

- Dark theme (`bg-neutral-950`, `text-neutral-100`)
- Monospaced font for numerics (`font-mono`)
- No emoji
- No loading spinners that block the view — use skeleton shimmer in side panel + cards
- Empty states: "No events match your filters" with a reset button

## Error states

- If Supabase env vars are missing → top banner "Configure NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY in your environment."
- If a query fails → tiny inline error per panel, do not crash the page.

## Files to generate

- `app/layout.tsx` — dark theme, top bar
- `app/page.tsx` — world map page
- `app/articles/page.tsx` — articles page
- `lib/supabase.ts` — Supabase client singleton
- `lib/queries.ts` — query helpers
- `components/WorldMap.tsx`
- `components/CountryPanel.tsx`
- `components/EventCard.tsx`
- `components/TopBar.tsx`
- `components/Filters.tsx`

Make it production-ready. Type all props. Use server components where possible; mark map / interactive components `"use client"`.
