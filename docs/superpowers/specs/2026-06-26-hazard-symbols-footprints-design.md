# Hazard markers: per-type symbols + zoom-reveal footprints + score gauge

Date: 2026-06-26
Branch: `fix/map-terrain-hillshade` (PR #204)
Status: approved design

## Problem

The map shows hazards as red/orange concentric **glow rings** (an emphasis ring +
radar ping on notable quakes). The user finds them noisy and annoying, and they
carry no information beyond "a quake is here." Meanwhile the GDACS / GDELT maps the
user wants to emulate do two things our map doesn't:

1. **Per-type symbols** — quake = waveform, cyclone = spiral, fire = flame, flood =
   water, volcano = volcano — colored by alert level (green / orange / red).
2. **Zoom-reveal footprints** — zoomed out you see only the pin; zoom in and the
   event's real *extent* appears (ShakeMap intensity contours for quakes, burn-scar
   polygon for fires). Small events are invisible far out and reveal on zoom-in.

The basemap itself (topo hillshade, PR #204) is **not** a problem and stays.

## Data reality

Confirmed against the live local API (`:8000`). We store **points only**:

- **USGS quake** payload: `magnitude`, `depth_km`, `place`, `alert`, `felt`,
  `tsunami`, `usgs_id`. No geometry.
- **GDACS** payload: `event_type` (EQ/WF/TC/FL/VO), `alert_level`
  (Green/Orange/Red), `magnitude`, `depth_km`, `severity_raw` (free text, e.g.
  `"Green impact for forestfire in 8028 ha"`), `iso3`, `country_name`, `from_date`,
  `to_date`, `gdacs_event_id`, `link`. No geometry.

No footprint geometry is stored anywhere. Real ShakeMap / burn polygons would need
new backend fetchers + per-event caching and only exist for big events.

**Decision: synthesize footprints from the point data we already have.** Frontend
only, no new fetchers, works for every event offline. It is an approximation of the
GDACS look, not the real product geometry.

## Architecture — Hybrid (chosen)

- **Footprints** → MapLibre GeoJSON `Source` + `Layer` (fill + line). Geographic, so
  they scale with zoom natively, support `minzoom` reveal + opacity fade, and stay
  fast for the ~180 hazard events on screen.
- **Pins / symbols** → keep HTML React `Marker`s (current pattern), reusing the
  existing marker-click → `EventDetailCard` wiring. Swap the glow-ring visual for a
  small GDACS-style square pin with a per-type icon.

Rejected: all-MapLibre-native (needs a built icon sprite + click rewrite via
`queryRenderedFeatures`, more work, less reuse); all-DOM footprints (DOM can't scale
geographically — would require manual pixel-radius math every zoom).

## Components

### 1. Hazard taxonomy — `lib/hazardSymbols.ts` (new)

Single source of truth mapping an event → `{ kind, icon, color, footprint }`.

- `kind`: `"EQ" | "WF" | "TC" | "FL" | "VO" | "other"`, derived from
  `payload.event_type` (GDACS) or source (`usgs-quake` → EQ, `nasa-firms` → WF).
- `icon`: a `lucide-react` icon component per kind (already a dependency):
  - EQ → `Activity` (waveform), WF → `Flame`, TC → `Wind`/`Tornado` (spiral),
    FL → `Droplets`, VO → `Triangle`/`Mountain`, other → filled dot.
- `color`: from `alert_level` (Green `#22c55e` / Orange `#f97316` / Red `#ef4444`);
  USGS has no alert → magnitude bands (`<4.5` green, `4.5–6` orange, `≥6` red).
- `footprint`: parameters for the synthesized geometry (see §2), or `null`.

### 2. Footprint geometry — `lib/footprints.ts` (new)

Pure functions, no map dependency, fully unit-testable. Returns a GeoJSON
`FeatureCollection` of polygon rings for a given event.

- **`circlePolygon(lon, lat, radiusKm, steps=64)`** — point buffer → polygon ring
  (equirectangular small-angle approximation; good enough at event scale, no new
  dep).
- **Quakes — `quakeContours(lon, lat, magnitude, depthKm)`**: 4–5 nested rings, one
  per MMI band. Felt radius per band from a magnitude+depth attenuation
  approximation (e.g. an IPE-style `R(MMI) = f(M, depth)` giving larger radii for
  bigger / shallower quakes). Each ring carries a `band` prop (green→red) for paint.
- **Fires — `fireExtent(lon, lat, areaHa)`**: single circle,
  `r_km = √(areaHa·0.01/π)`. `areaHa` parsed from `severity_raw` (`/in ([\d.]+) ha/`).
- **TC / FL / VO — `severityExtent(lon, lat, severity)`**: one circle whose radius
  comes from a severity→km band table.

### 3. Map rendering — `components/MapPane.tsx` (edit)

- **Remove** the glow-ring + radar-ping block in `EventMarker` (lines ~111–134) and
  the `ring` plumbing in `lib/markers.ts`.
- **Add a `HazardFootprints` layer**: build one merged `FeatureCollection` (memoized)
  from the visible hazard events, render as a MapLibre `Source` with a `fill` layer
  (low opacity, color by `band`/`color`) + a `line` layer (the contour outline).
  `minzoom ≈ 4`; opacity ramps in via a zoom expression so it's invisible when
  zoomed out and reveals on zoom-in.
- **Pin**: `EventMarker` renders the per-type icon from `hazardSymbols` in a small
  GDACS-style square, colored by alert. Always visible at all zooms.

### 4. Detail panel — `components/EventDetailCard.tsx` (edit)

Add a GDACS-style **score gauge**: a 0–3 horizontal bar (green / orange / red bands)
with a marker at `severity·3`. Add metadata rows where present: GDACS/USGS id,
country, from/to dates, magnitude, depth, burned-area ha. Reuse existing card
layout; no new route or modal.

## Data flow

```
event (point + payload)
  → hazardSymbols(event)         → { kind, icon, color, footprintParams }
      → EventMarker              → square pin + per-type icon (always on)
      → footprints(event)        → GeoJSON rings  (collected per pane)
          → HazardFootprints     → MapLibre fill+line, minzoom reveal
  → click → EventDetailCard      → score gauge + metadata
```

## Scope

- One PR, on **#204** (`fix/map-terrain-hillshade`), alongside the topo basemap.
- **FIRMS** 54k point-fires stay as the small dots they are (separate firehose, not
  part of this complaint). GDACS WF events get the flame symbol + burn circle.
- Out of scope (possible later pass): real ShakeMap / GDACS polygon geometry;
  cyclone track lines; per-event on-demand geometry fetching.

## Testing

- **vitest** (`__tests__/footprints.test.ts`): ring radii increase with magnitude,
  decrease with depth; `fireExtent` ha→radius math; `circlePolygon` is closed and has
  the right vertex count.
- **vitest** (`__tests__/hazardSymbols.test.ts`): kind derivation per source /
  event_type; color per alert level + USGS magnitude bands.
- **Headless screenshot**: zoomed-out shows pins only; zoomed-in reveals quake rings
  + fire circles on the topo basemap; no glow rings remain.

## Risks

- **Synthesized ≠ real** — radii are approximations; label the panel honestly
  ("estimated extent"), don't imply it's the official ShakeMap.
- **Perf** — ~180 hazard footprints is fine; if it ever grows, cap by zoom/severity.
- **Attenuation formula** — pick a documented IPE (e.g. Allen/Wald style) and cite it
  in a comment so the radii are defensible, not magic numbers.
