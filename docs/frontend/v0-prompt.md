# v0.dev prompt — OSINT World Monitor dashboard

Copy the section below verbatim into [v0.dev](https://v0.dev).

---

Build a Next.js 15 dashboard called "OSINT World Monitor". Dark theme. Inspired by WorldMonitor, Shadowbroker, and Palantir Foundry — analytical, dense, fluid, real-time. Two split panes side by side: a flat world map on the left, a 3D rotating globe on the right. Each pane is independently filterable and independently scrubbable through time, but they share data sources. Events fade in when new and fade out as they age. Layout dynamic, no chrome wasted.

## Stack

- Next.js 15 App Router, TypeScript, strict mode
- Tailwind CSS
- shadcn/ui for buttons / sliders / checkboxes / popovers
- `@supabase/supabase-js` for data
- `react-map-gl` (MapLibre flavour, no Mapbox token) for the left flat map
- `react-globe.gl` (Three.js under the hood) for the right 3D globe
- Supabase **Realtime subscriptions** for new events
- `swr` for periodic refetches as a fallback
- `framer-motion` for fade / pulse animations
- `date-fns` for time formatting
- `zustand` for per-pane filter state (one store for the left pane, one for the right)

## Environment

```
NEXT_PUBLIC_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=eyJ...
```

Initialise the Supabase client in `lib/supabase.ts`. Subscribe to the `events` table changes in a top-level provider so both panes share the same realtime stream.

## Database (read-only via anon RLS)

**events**: `id, source, source_event_id, occurred_at, fetched_at, category, severity (0..1), keywords text[], country (ISO alpha-2), lat, lon, payload jsonb`

**scores**: `country, bucket_start, bucket_length, score_name, score_value (0..1), components jsonb, method_version`

`events.payload` shape per source:
- GDELT — `{ goldstein, num_mentions, avg_tone, source_url, event_root_code }`
- USGS — `{ place, magnitude, alert, depth_km }`
- GDACS — `{ event_type, alert_level, country_name, severity_raw, link }`
- NASA FIRMS — `{ brightness, frp, daynight }`
- yfinance — `{ ticker, close, drawdown_pct }`

`events.category` ∈ { market, geopolitical, hazard, weather, tracking, space, news, cyber, mesh }.

## Layout

Single full-viewport page. No header bar wasting height. Top-left small logo overlay reads "OSINT WORLD MONITOR · LIVE". Bottom-left tiny timestamp showing the latest event time in the database.

Two panes, 50 / 50 horizontal split, resizable via a thin draggable divider:

| Left pane | Right pane |
|---|---|
| Flat 2D map (MapLibre dark style: `https://tiles.openfreemap.org/styles/dark`) | 3D rotating globe (`react-globe.gl`), starfield background `#000010`, slow auto-rotation |

Each pane has:

1. A **filter rail** along its outer edge (left edge for the map, right edge for the globe). The rail is icon-only by default; clicking expands it into a 280-px panel with full controls. Filters are independent per pane — toggling on the map does not affect the globe.
2. A **time scrubber** docked at the bottom of the pane (8 % of pane height). Scrubber controls: play / pause, speed multiplier (1×, 10×, 100×, MAX), and a draggable thumb on a 30-day window slider. When playing, the visible-event window moves forward in real time at the chosen speed. When paused, the thumb stops; the map shows events whose `occurred_at` falls within the visible window.

## Filter rail contents (identical schema on both panes)

A vertical list of toggle pills, each with a small coloured dot:

- **Geopolitical events** (GDELT) — grey
- **Markets** (yfinance) — green
- **Earthquakes** (USGS) — red
- **Multi-hazard alerts** (GDACS) — orange
- **Active fires** (NASA FIRMS) — yellow

Below the toggles:

- **Severity** range slider (two thumbs, 0 .. 1)
- **Country** multi-select combobox (typeahead from distinct `country` values)
- **Keyword** search input
- **Reset** button at the bottom

Each toggle's state lives in the per-pane zustand store. The map / globe query Supabase filtered by the active toggles and severity / country / keyword.

## Visual encoding

Both panes share the colour scale; only the projection differs.

### Country shading (left pane only — flat map has country polygons)

For each country, fetch the latest `score_value` from `scores`. Apply a thin polygon fill:

- 0.00 → 0.40 = green `rgba(34,197,94,0.12)` (calm)
- 0.40 → 0.60 = yellow `rgba(234,179,8,0.18)` (watch)
- 0.60 → 0.80 = orange `rgba(249,115,22,0.24)` (warning)
- 0.80 → 1.00 = red `rgba(239,68,68,0.30)` (stress)

Use the world-countries GeoJSON from `https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson`. Join on ISO alpha-2.

### Event markers (both panes)

For each visible event, place a marker at (`lat`, `lon`):

- **Earthquake** — solid red circle, radius `clamp(payload.magnitude * 2, 4, 16)`, pulse outward for 1.5 s on first render
- **GDACS** — orange diamond, size mapped from `payload.alert_level`
- **Fire** — small yellow dot
- **GDELT** — grey circle, radius `clamp(payload.num_mentions / 50, 3, 10)` (only if `lat` present)
- **Market** — green circle on country centroid

### Fade

- Each marker has an `age` derived from `(now − occurred_at) / window_length`.
- Opacity decays linearly: `opacity = max(0.10, 1 - age)`.
- Glow ring on markers `age < 0.05`.
- Old markers (`age > 1`) are unmounted.

Use `framer-motion` `AnimatePresence` for mount / unmount animations (200 ms fade-in, 800 ms fade-out).

### Globe

`react-globe.gl` with:

- `globeImageUrl` = `//unpkg.com/three-globe/example/img/earth-night.jpg`
- `bumpImageUrl` = `//unpkg.com/three-globe/example/img/earth-topology.png`
- `backgroundColor` = `#000010`
- Stars rendered (`showAtmosphere = true`)
- Auto-rotate at 0.5 deg / sec (can be paused with a small icon on the globe pane)
- `pointsData` from the filtered events; `pointColor` mirrors marker color; `pointAltitude` mapped from severity (0..0.5 globe radius units)
- `arcsData` reserved for a future satellite layer (leave wired but empty)
- Click a point → small floating card with event details

## Realtime

In `lib/realtime.ts`, subscribe to:

```ts
supabase.channel('events-realtime')
  .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'events' }, payload => emit(payload.new))
  .subscribe()
```

Maintain a small in-memory ring buffer of the last 5000 events; both panes read from this. New events that match the current filter set animate in (`scale: 0 → 1`, opacity `0 → 1`, soft pulse). Existing events get re-evaluated against the current time window.

## Country side panel

Clicking a country (either pane) opens a thin floating right-side card with:

- Country name + flag + ISO code
- Latest composite score (large numeric, color from scale)
- Per-domain z-bars (market / geopolitical / hazard) from `components.z`
- Last 10 events in that country (small rows: time ago, source icon, severity dot, click to open `payload.source_url` if present)
- Close button

## Top overlays

- Top-left: "OSINT WORLD MONITOR · LIVE" small caps, white at 80 % opacity
- Top-right: small connection indicator — green dot if Supabase Realtime is connected, amber if reconnecting, red if disconnected
- Bottom-center thin status bar: "Showing N events in window | Map filter: hazards + geopolitical | Globe filter: hazards"

## Files to generate

- `app/layout.tsx` — dark theme, root provider
- `app/page.tsx` — split-pane layout, mounts both panes
- `app/providers.tsx` — Supabase Realtime + ring-buffer provider
- `lib/supabase.ts`
- `lib/realtime.ts`
- `lib/queries.ts` — `useEventsInWindow(filterStore, timeWindow)`, `useLatestScores()`
- `stores/leftPaneStore.ts` + `stores/rightPaneStore.ts` — zustand
- `components/SplitLayout.tsx`
- `components/MapPane.tsx`
- `components/GlobePane.tsx`
- `components/FilterRail.tsx`
- `components/TimeScrubber.tsx`
- `components/CountrySidePanel.tsx`
- `components/ConnectionIndicator.tsx`

## Polish rules

- Dark theme (`bg-neutral-950`, `text-neutral-100`)
- Monospaced font for numerics
- No emoji on UI; small inline SVG icons only
- No skeleton spinner blocking the whole viewport — only the side panel uses a shimmer
- No layout shift between panes when filters change — keep marker layers absolute-positioned
- All animation durations under 800 ms; nothing janky
- Keyboard: `[` and `]` to toggle left and right filter rails; spacebar plays / pauses whichever pane has focus
- Empty-state per pane: "No events match the current filters" in muted text, centred

## Error states

- Missing env vars → red banner at top: "Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"
- Realtime disconnect → connection indicator turns red, fall back to SWR-polled refetch every 30 s

Make it production-ready. Type everything. Mark interactive components `"use client"`. Server-render whatever can be server-rendered. No `any`. No TODOs.
