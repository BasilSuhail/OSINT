# Hazard Symbols + Zoom-Reveal Footprints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the noisy red/orange glow rings with GDACS-style per-type hazard symbols colored by alert level, plus synthesized zoom-reveal footprints (quake intensity contours, fire/extent circles) and a 0–3 score gauge in the detail panel.

**Architecture:** Hybrid render. Footprints are MapLibre GeoJSON `Source`/`Layer` (geographic, zoom-native reveal). Pins stay HTML React `Marker`s with per-type lucide icons. All geometry is synthesized client-side from the point data we already store — no new backend fetchers.

**Tech Stack:** Next.js 15, React, TypeScript, `react-map-gl/maplibre`, `lucide-react` (existing dep), vitest.

## Global Constraints

- Branch: `fix/map-terrain-hillshade` (PR #204). Do NOT create a new branch.
- TypeScript only; arrow functions, destructuring, optional chaining; match surrounding style.
- No new dependencies — `lucide-react@^1.16.0` is already present; geometry is hand-rolled (no turf).
- Frontend only. No backend / migration / fetcher changes.
- Footprints are an **approximation** — comments must say so; never imply official ShakeMap geometry.
- Colors: Green `#22c55e`, Orange `#f97316`, Red `#ef4444`.
- Tests live in `osint-frontend/__tests__/*.test.ts`; run with `pnpm test` (vitest) from `osint-frontend/`.

---

### Task 1: Footprint geometry — pure functions

**Files:**
- Create: `osint-frontend/lib/footprints.ts`
- Test: `osint-frontend/__tests__/footprints.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `circlePolygon(lon: number, lat: number, radiusKm: number, steps?: number): [number, number][]` — closed ring (first === last).
  - `feltRadiusKm(magnitude: number, depthKm: number, mmi: number): number`
  - `parseBurnedHa(severityRaw: string | null | undefined): number | null`
  - `fireRadiusKm(areaHa: number): number`
  - `type FootprintBand = { mmi: number; color: string; radiusKm: number }`
  - `quakeBands(magnitude: number, depthKm: number): FootprintBand[]`

- [ ] **Step 1: Write the failing test**

```typescript
// osint-frontend/__tests__/footprints.test.ts
import { describe, expect, it } from "vitest"
import {
  circlePolygon,
  feltRadiusKm,
  parseBurnedHa,
  fireRadiusKm,
  quakeBands,
} from "@/lib/footprints"

describe("circlePolygon", () => {
  it("returns a closed ring with steps+1 points", () => {
    const ring = circlePolygon(0, 0, 100, 32)
    expect(ring).toHaveLength(33)
    expect(ring[0]).toEqual(ring[ring.length - 1])
  })

  it("offsets roughly radius/111km in degrees at the equator", () => {
    const ring = circlePolygon(0, 0, 111, 4)
    const lons = ring.map((p) => p[0])
    expect(Math.max(...lons)).toBeCloseTo(1, 1) // ~1 degree east
  })
})

describe("feltRadiusKm", () => {
  it("grows with magnitude", () => {
    expect(feltRadiusKm(7, 10, 4)).toBeGreaterThan(feltRadiusKm(5, 10, 4))
  })
  it("shrinks as the target intensity rises", () => {
    expect(feltRadiusKm(6.5, 10, 7)).toBeLessThan(feltRadiusKm(6.5, 10, 4))
  })
  it("shrinks with depth (surface projection)", () => {
    expect(feltRadiusKm(6.5, 100, 5)).toBeLessThan(feltRadiusKm(6.5, 10, 5))
  })
  it("returns 0 when the band intensity exceeds the epicentre", () => {
    expect(feltRadiusKm(3, 10, 9)).toBe(0)
  })
})

describe("parseBurnedHa", () => {
  it("pulls hectares out of GDACS severity text", () => {
    expect(parseBurnedHa("Green impact for forestfire in 8028 ha")).toBe(8028)
  })
  it("handles thousands separators", () => {
    expect(parseBurnedHa("... in 12,500 ha")).toBe(12500)
  })
  it("returns null when no ha present", () => {
    expect(parseBurnedHa("Orange alert")).toBeNull()
    expect(parseBurnedHa(null)).toBeNull()
  })
})

describe("fireRadiusKm", () => {
  it("derives radius from area (8028 ha ≈ 5 km)", () => {
    expect(fireRadiusKm(8028)).toBeCloseTo(5.05, 1)
  })
})

describe("quakeBands", () => {
  it("returns only bands with a positive radius, strongest last", () => {
    const bands = quakeBands(6.5, 10)
    expect(bands.length).toBeGreaterThan(0)
    for (const b of bands) expect(b.radiusKm).toBeGreaterThan(0)
    // radii strictly decrease as mmi rises
    const radii = bands.map((b) => b.radiusKm)
    const sorted = [...radii].sort((a, z) => z - a)
    expect(radii).toEqual(sorted)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd osint-frontend && pnpm test footprints`
Expected: FAIL — `Cannot find module '@/lib/footprints'`.

- [ ] **Step 3: Write minimal implementation**

```typescript
// osint-frontend/lib/footprints.ts
// Synthesized hazard footprints — drawn from the point data we already store
// (magnitude, depth, burned-area text). These are VISUAL APPROXIMATIONS of the
// GDACS/USGS products, not the official ShakeMap / burn geometry. Pure functions,
// no map dependency, so they're trivially unit-testable.

const KM_PER_DEG_LAT = 110.574

/** Closed polygon ring approximating a circle of `radiusKm` around (lon,lat).
 *  Equirectangular small-angle projection — accurate enough at event scale. */
export function circlePolygon(
  lon: number,
  lat: number,
  radiusKm: number,
  steps = 64,
): [number, number][] {
  const kmPerDegLon = 111.32 * Math.cos((lat * Math.PI) / 180)
  const ring: [number, number][] = []
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * 2 * Math.PI
    const dLon = (radiusKm / kmPerDegLon) * Math.cos(a)
    const dLat = (radiusKm / KM_PER_DEG_LAT) * Math.sin(a)
    ring.push([lon + dLon, lat + dLat])
  }
  ring[ring.length - 1] = ring[0] // exact closure
  return ring
}

/** Surface radius (km) at which modified-Mercalli intensity `mmi` is felt for a
 *  quake of moment magnitude `magnitude` at `depthKm`. Simplified intensity-
 *  prediction inversion: epicentral intensity ~1.5M, log-distance decay, then
 *  projected from hypocentral to surface distance. Approximation, not seismology. */
export function feltRadiusKm(magnitude: number, depthKm: number, mmi: number): number {
  const epicentralIntensity = 1.5 * magnitude - 1.0
  if (mmi >= epicentralIntensity) return 0
  const rHypo = Math.pow(10, (epicentralIntensity - mmi) / 2.0)
  const rSurfSq = rHypo * rHypo - depthKm * depthKm
  return rSurfSq > 0 ? Math.sqrt(rSurfSq) : 0
}

/** Hectares from GDACS `severity_raw` free text (e.g. "... in 8028 ha"). */
export function parseBurnedHa(severityRaw: string | null | undefined): number | null {
  if (!severityRaw) return null
  const m = severityRaw.match(/([\d.,]+)\s*ha\b/i)
  if (!m) return null
  const n = Number(m[1].replace(/,/g, ""))
  return Number.isFinite(n) ? n : null
}

/** Radius (km) of a circle whose area equals `areaHa` hectares (1 ha = 0.01 km²). */
export function fireRadiusKm(areaHa: number): number {
  return Math.sqrt((areaHa * 0.01) / Math.PI)
}

export type FootprintBand = { mmi: number; color: string; radiusKm: number }

// MMI band → ring colour (felt → destructive), green to red.
const MMI_BANDS: { mmi: number; color: string }[] = [
  { mmi: 4, color: "#22c55e" },
  { mmi: 5, color: "#eab308" },
  { mmi: 6, color: "#f97316" },
  { mmi: 7, color: "#ef4444" },
]

/** Concentric intensity bands for a quake, largest (weakest) first, dropping any
 *  band whose surface radius collapses to 0. */
export function quakeBands(magnitude: number, depthKm: number): FootprintBand[] {
  return MMI_BANDS.map(({ mmi, color }) => ({
    mmi,
    color,
    radiusKm: feltRadiusKm(magnitude, depthKm, mmi),
  })).filter((b) => b.radiusKm > 0)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd osint-frontend && pnpm test footprints`
Expected: PASS (all describe blocks green).

- [ ] **Step 5: Commit**

```bash
git add osint-frontend/lib/footprints.ts osint-frontend/__tests__/footprints.test.ts
git commit -m "feat(map): synthesized hazard footprint geometry helpers"
```

---

### Task 2: Hazard taxonomy — kind / color / icon / footprint

**Files:**
- Create: `osint-frontend/lib/hazardSymbols.ts`
- Test: `osint-frontend/__tests__/hazardSymbols.test.ts`

**Interfaces:**
- Consumes: `EventRow` from `@/lib/types`; `circlePolygon`, `quakeBands`, `parseBurnedHa`, `fireRadiusKm` from `@/lib/footprints`.
- Produces:
  - `type HazardKind = "EQ" | "WF" | "TC" | "FL" | "VO" | "other"`
  - `type HazardIcon = "activity" | "flame" | "wind" | "droplets" | "triangle" | "dot"`
  - `hazardKind(ev: EventRow): HazardKind`
  - `hazardColor(ev: EventRow): string`
  - `hazardIcon(kind: HazardKind): HazardIcon`
  - `footprintFeatures(ev: EventRow): GeoJSON.Feature[]` — polygon features with `properties.color` and `properties.fillOpacity`; `[]` when none.

- [ ] **Step 1: Write the failing test**

```typescript
// osint-frontend/__tests__/hazardSymbols.test.ts
import { describe, expect, it } from "vitest"
import { hazardKind, hazardColor, hazardIcon, footprintFeatures } from "@/lib/hazardSymbols"
import type { EventRow } from "@/lib/types"

function row(p: Partial<EventRow>): EventRow {
  return {
    id: 1, source: "gdacs", source_event_id: "x", occurred_at: "2026-06-24T00:00:00Z",
    category: "hazard", severity: 0.5, confidence: null, keywords: [],
    country: "VE", lat: 10, lon: -67, payload: {}, ...p,
  } as EventRow
}

describe("hazardKind", () => {
  it("maps USGS to EQ", () => expect(hazardKind(row({ source: "usgs-quake" }))).toBe("EQ"))
  it("maps FIRMS to WF", () => expect(hazardKind(row({ source: "nasa-firms" }))).toBe("WF"))
  it("reads GDACS event_type", () => {
    expect(hazardKind(row({ payload: { event_type: "TC" } }))).toBe("TC")
    expect(hazardKind(row({ payload: { event_type: "FL" } }))).toBe("FL")
  })
  it("falls back to other", () => expect(hazardKind(row({ source: "gdelt", payload: {} }))).toBe("other"))
})

describe("hazardColor", () => {
  it("uses GDACS alert level", () => {
    expect(hazardColor(row({ payload: { alert_level: "Red" } }))).toBe("#ef4444")
    expect(hazardColor(row({ payload: { alert_level: "Orange" } }))).toBe("#f97316")
    expect(hazardColor(row({ payload: { alert_level: "Green" } }))).toBe("#22c55e")
  })
  it("falls back to USGS magnitude bands", () => {
    expect(hazardColor(row({ source: "usgs-quake", payload: { magnitude: 6.4 } }))).toBe("#ef4444")
    expect(hazardColor(row({ source: "usgs-quake", payload: { magnitude: 5.0 } }))).toBe("#f97316")
    expect(hazardColor(row({ source: "usgs-quake", payload: { magnitude: 3.0 } }))).toBe("#22c55e")
  })
})

describe("hazardIcon", () => {
  it("maps kind to a lucide key", () => {
    expect(hazardIcon("EQ")).toBe("activity")
    expect(hazardIcon("WF")).toBe("flame")
    expect(hazardIcon("other")).toBe("dot")
  })
})

describe("footprintFeatures", () => {
  it("emits multiple ring features for a strong quake", () => {
    const f = footprintFeatures(row({ source: "usgs-quake", payload: { magnitude: 6.5, depth_km: 10 } }))
    expect(f.length).toBeGreaterThan(1)
    expect(f[0].geometry.type).toBe("Polygon")
    expect(f[0].properties?.color).toBeTypeOf("string")
  })
  it("emits one circle for a fire with a burned area", () => {
    const f = footprintFeatures(row({ payload: { event_type: "WF", severity_raw: "... in 8028 ha", alert_level: "Green" } }))
    expect(f).toHaveLength(1)
  })
  it("emits nothing when there is no usable geometry", () => {
    expect(footprintFeatures(row({ source: "gdelt", payload: {}, lat: null, lon: null }))).toHaveLength(0)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd osint-frontend && pnpm test hazardSymbols`
Expected: FAIL — `Cannot find module '@/lib/hazardSymbols'`.

- [ ] **Step 3: Write minimal implementation**

```typescript
// osint-frontend/lib/hazardSymbols.ts
// One source of truth: event -> { kind, color, icon, footprint }. Drives both the
// map pin (icon + colour) and the synthesized footprint layer.
import type { EventRow } from "./types"
import { circlePolygon, fireRadiusKm, parseBurnedHa, quakeBands } from "./footprints"

export type HazardKind = "EQ" | "WF" | "TC" | "FL" | "VO" | "other"
export type HazardIcon = "activity" | "flame" | "wind" | "droplets" | "triangle" | "dot"

const GREEN = "#22c55e"
const ORANGE = "#f97316"
const RED = "#ef4444"

function payload(ev: EventRow): Record<string, unknown> {
  return (ev.payload ?? {}) as Record<string, unknown>
}

export function hazardKind(ev: EventRow): HazardKind {
  const src = (ev.source ?? "").toLowerCase()
  if (src.includes("usgs")) return "EQ"
  if (src.includes("firms")) return "WF"
  const t = String(payload(ev).event_type ?? "").toUpperCase()
  if (t === "EQ" || t === "WF" || t === "TC" || t === "FL" || t === "VO") return t
  return "other"
}

export function hazardColor(ev: EventRow): string {
  const alert = String(payload(ev).alert_level ?? "").toLowerCase()
  if (alert === "red") return RED
  if (alert === "orange") return ORANGE
  if (alert === "green") return GREEN
  const mag = Number(payload(ev).magnitude ?? 0)
  if (mag >= 6) return RED
  if (mag >= 4.5) return ORANGE
  return GREEN
}

export function hazardIcon(kind: HazardKind): HazardIcon {
  switch (kind) {
    case "EQ": return "activity"
    case "WF": return "flame"
    case "TC": return "wind"
    case "FL": return "droplets"
    case "VO": return "triangle"
    default: return "dot"
  }
}

// Single extent circle radius (km) by severity for non-quake / non-fire hazards.
function severityRadiusKm(severity: number): number {
  if (severity >= 0.66) return 120
  if (severity >= 0.33) return 60
  return 20
}

function poly(ring: [number, number][], color: string, fillOpacity: number): GeoJSON.Feature {
  return {
    type: "Feature",
    properties: { color, fillOpacity },
    geometry: { type: "Polygon", coordinates: [ring] },
  }
}

/** Synthesized footprint polygons for an event (largest first so smaller, hotter
 *  rings paint on top). Empty when the event has no coordinates or no usable size. */
export function footprintFeatures(ev: EventRow): GeoJSON.Feature[] {
  const lon = ev.lon
  const lat = ev.lat
  if (lon == null || lat == null) return []
  const kind = hazardKind(ev)
  const p = payload(ev)

  if (kind === "EQ") {
    const mag = Number(p.magnitude ?? 0)
    const depth = Number(p.depth_km ?? 10) || 10
    if (mag <= 0) return []
    return quakeBands(mag, depth).map((b) =>
      poly(circlePolygon(lon, lat, b.radiusKm), b.color, 0.12),
    )
  }

  if (kind === "WF") {
    const ha = parseBurnedHa(typeof p.severity_raw === "string" ? p.severity_raw : null)
    if (!ha) return []
    return [poly(circlePolygon(lon, lat, fireRadiusKm(ha)), hazardColor(ev), 0.25)]
  }

  // TC / FL / VO / other: a single severity-sized extent circle.
  const r = severityRadiusKm(Number(ev.severity ?? 0))
  return [poly(circlePolygon(lon, lat, r), hazardColor(ev), 0.15)]
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd osint-frontend && pnpm test hazardSymbols`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add osint-frontend/lib/hazardSymbols.ts osint-frontend/__tests__/hazardSymbols.test.ts
git commit -m "feat(map): hazard taxonomy — kind/color/icon + synthesized footprints"
```

---

### Task 3: Drop the glow ring; render per-type icon pins

**Files:**
- Modify: `osint-frontend/lib/markers.ts` (remove `ring` field + `isNotableQuake` + `EQ_RING_MIN_MAG`)
- Modify: `osint-frontend/__tests__/markers.test.ts` (delete the ring describe block)
- Modify: `osint-frontend/components/MapPane.tsx` (`EventMarker`: remove ring JSX, render hazard icon)

**Interfaces:**
- Consumes: `hazardKind`, `hazardIcon`, `hazardColor` from `@/lib/hazardSymbols`.
- Produces: `MarkerStyle` without `ring`; `EventMarker` renders a lucide icon for hazard events.

- [ ] **Step 1: Update markers.ts — remove ring**

In `osint-frontend/lib/markers.ts`: delete the `ring: boolean` field from `MarkerStyle`, delete `EQ_RING_MIN_MAG`, delete the entire `isNotableQuake` function, remove `const ring = isNotableQuake(...)` and every `, ring` from the returned objects.

Resulting `MarkerStyle`:
```typescript
export interface MarkerStyle {
  shape: MarkerShape
  size: number
  color: string
}
```
And each `return { shape: ..., size: ..., color }` (no `ring`).

- [ ] **Step 2: Update markers.test.ts**

Delete the whole `describe("markerStyle earthquake emphasis ring", ...)` block. If the file is now empty of tests, replace its body with a minimal shape test:
```typescript
import { describe, expect, it } from "vitest"
import { markerStyle } from "@/lib/markers"
import type { EventRow } from "@/lib/types"

describe("markerStyle", () => {
  it("sizes a USGS quake by magnitude", () => {
    const s = markerStyle({
      id: 1, source: "usgs-quake", source_event_id: "x", occurred_at: "2026-06-24T00:00:00Z",
      category: "hazard", severity: 0.6, confidence: null, keywords: [],
      country: "VE", lat: 10, lon: -67, payload: { magnitude: 6 },
    } as EventRow)
    expect(s.shape).toBe("circle")
    expect(s.color).toBeTypeOf("string")
  })
})
```

- [ ] **Step 3: Run tests to verify they pass (red→green for the removal)**

Run: `cd osint-frontend && pnpm test markers`
Expected: PASS (no ring references remain).

- [ ] **Step 4: Update EventMarker in MapPane.tsx**

At the top of `osint-frontend/components/MapPane.tsx` add imports:
```typescript
import { Activity, Flame, Wind, Droplets, Triangle } from "lucide-react"
import { hazardColor, hazardIcon, hazardKind, type HazardIcon } from "@/lib/hazardSymbols"
```

Add an icon lookup near the top of the file (after imports, module scope):
```typescript
const HAZARD_ICONS: Record<Exclude<HazardIcon, "dot">, typeof Activity> = {
  activity: Activity,
  flame: Flame,
  wind: Wind,
  droplets: Droplets,
  triangle: Triangle,
}
```

In `EventMarker`, replace the whole ring block (the `{style.ring && ( ... )}` JSX, lines ~111–134) and the inner dot `<span>` with: hazard events (category `hazard`/`weather`) render a small square pin + icon; everything else keeps the existing dot/diamond. Concretely, inside the `motion.div`, replace the ring `<>...</>` and the trailing dot `<span>` with:

```tsx
{(() => {
  const kind = hazardKind(ev)
  const iconKey = hazardIcon(kind)
  const color = hazardColor(ev)
  if (iconKey !== "dot" && !clusterable) {
    const Icon = HAZARD_ICONS[iconKey]
    return (
      <span
        className="grid place-items-center rounded-sm"
        style={{
          width: 18,
          height: 18,
          backgroundColor: color,
          boxShadow: `0 0 4px ${color}aa`,
          border: "1px solid rgba(255,255,255,0.5)",
        }}
      >
        <Icon size={12} color="#0a0a0a" strokeWidth={2.5} aria-hidden />
      </span>
    )
  }
  // non-hazard: keep the simple dot/diamond
  return (
    <span
      className="block"
      style={{
        width: size,
        height: size,
        backgroundColor: style.color,
        borderRadius: style.shape === "diamond" ? 2 : "9999px",
        transform: style.shape === "diamond" ? "rotate(45deg)" : undefined,
        boxShadow: `0 0 3px ${style.color}`,
      }}
    />
  )
})()}
```

(Delete the old `{style.ring && (...)}` block entirely.)

- [ ] **Step 5: Verify tsc + lint**

Run: `cd osint-frontend && npx tsc --noEmit && npx eslint lib/markers.ts components/MapPane.tsx`
Expected: no errors (pre-existing warnings elsewhere are fine).

- [ ] **Step 6: Commit**

```bash
git add osint-frontend/lib/markers.ts osint-frontend/__tests__/markers.test.ts osint-frontend/components/MapPane.tsx
git commit -m "feat(map): per-type hazard icon pins, remove glow ring"
```

---

### Task 4: Zoom-reveal footprint layer

**Files:**
- Modify: `osint-frontend/components/MapPane.tsx` (build merged FeatureCollection from visible hazards, render Source + fill/line layers under markers)

**Interfaces:**
- Consumes: `footprintFeatures` from `@/lib/hazardSymbols`; the existing `positioned` array of `{ ev, lat, lon }`.
- Produces: a memoized `hazardFootprints: GeoJSON.FeatureCollection` + two MapLibre layers.

- [ ] **Step 1: Build the FeatureCollection (memoized)**

In `MapPane`, after the `positioned` useMemo, add:
```typescript
import { footprintFeatures } from "@/lib/hazardSymbols" // (add to imports)

const hazardFootprints = useMemo<GeoJSON.FeatureCollection>(() => {
  const features: GeoJSON.Feature[] = []
  for (const { ev } of positioned) {
    if (ev.category !== "hazard" && ev.category !== "weather") continue
    for (const f of footprintFeatures(ev)) features.push(f)
  }
  return { type: "FeatureCollection", features }
}, [positioned])
```

- [ ] **Step 2: Render the layers (reveal on zoom-in)**

Inside `<MapGL>`, immediately AFTER the terrain hillshade `<Source>` and BEFORE the `{scoredGeo && (...)}` countries source, add:
```tsx
<Source id="hazard-footprints" type="geojson" data={hazardFootprints}>
  <Layer
    id="hazard-footprint-fill"
    type="fill"
    minzoom={4}
    paint={{
      "fill-color": ["get", "color"],
      "fill-opacity": [
        "interpolate", ["linear"], ["zoom"],
        4, 0,
        6, ["get", "fillOpacity"],
      ],
    }}
  />
  <Layer
    id="hazard-footprint-line"
    type="line"
    minzoom={4}
    paint={{
      "line-color": ["get", "color"],
      "line-width": 1,
      "line-opacity": ["interpolate", ["linear"], ["zoom"], 4, 0, 6, 0.8],
    }}
  />
</Source>
```

- [ ] **Step 3: Verify tsc**

Run: `cd osint-frontend && npx tsc --noEmit`
Expected: no errors. (If `GeoJSON` namespace is unresolved, it ships with `@types/geojson` via maplibre; if tsc complains, import the type: `import type { FeatureCollection, Feature } from "geojson"` and use those names.)

- [ ] **Step 4: Visual check (headless screenshot)**

Run the screenshot script (dev server must be on :3000):
```bash
cd /Users/basilsuhail/folders/OSINT/scratch/pw && node shot-relief.mjs
```
Open `scratchpad/relief-zoom.png`: zoomed-in view shows colored footprint rings/circles on hazards; `relief-world.png` (zoomed out) shows pins only, no footprints. Confirm no glow rings remain.

- [ ] **Step 5: Commit**

```bash
git add osint-frontend/components/MapPane.tsx
git commit -m "feat(map): zoom-reveal synthesized hazard footprints"
```

---

### Task 5: Detail panel — GDACS 0–3 score gauge + metadata

**Files:**
- Modify: `osint-frontend/components/EventDetailCard.tsx` (add gauge + metadata rows for hazard events)

**Interfaces:**
- Consumes: `ev.severity` (0–1) and payload fields (`magnitude`, `depth_km`, `country_name`, `from_date`, `to_date`, `gdacs_event_id`, `usgs_id`, `severity_raw`).
- Produces: a `ScoreGauge` sub-component + a metadata `<dl>` rendered for hazard/weather events.

- [ ] **Step 1: Add the gauge sub-component**

In `osint-frontend/components/EventDetailCard.tsx`, add before the `EventDetailCard` export:
```tsx
/** GDACS-style 0–3 alert gauge. We store severity as 0–1; scale to 0–3 so the
 *  marker sits in green (<1) / orange (1–2) / red (>2) like the GDACS score bar. */
function ScoreGauge({ severity }: { severity: number }) {
  const score = Math.max(0, Math.min(3, severity * 3))
  const pct = (score / 3) * 100
  return (
    <div className="mt-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-400">
          Alert score
        </span>
        <span className="font-mono text-[11px] tabular-nums text-neutral-200">
          {score.toFixed(1)} / 3
        </span>
      </div>
      <div className="relative h-2 w-full overflow-hidden rounded-full">
        <div className="absolute inset-0 flex">
          <div className="h-full flex-1" style={{ backgroundColor: "#22c55e" }} />
          <div className="h-full flex-1" style={{ backgroundColor: "#f97316" }} />
          <div className="h-full flex-1" style={{ backgroundColor: "#ef4444" }} />
        </div>
        <div
          className="absolute top-1/2 h-3 w-3 -translate-y-1/2 -translate-x-1/2 rounded-full border-2 border-white bg-neutral-900"
          style={{ left: `${pct}%` }}
          aria-hidden
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Render gauge + metadata for hazard events**

In the `EventDetailCard` JSX body, find where the title/SourceSignals render and add — gated on `event.category === "hazard" || event.category === "weather"` — the gauge and a metadata list. Use the existing `payload` access pattern (`const p = event.payload as Record<string, unknown>`):
```tsx
{(event.category === "hazard" || event.category === "weather") && (
  <>
    <ScoreGauge severity={Number(event.severity ?? 0)} />
    <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11px]">
      {[
        ["Country", (p.country_name as string) || event.country],
        ["Magnitude", p.magnitude != null ? `M${Number(p.magnitude).toFixed(1)}` : null],
        ["Depth", p.depth_km != null ? `${Number(p.depth_km).toFixed(0)} km` : null],
        ["Burned area", typeof p.severity_raw === "string" ? p.severity_raw : null],
        ["ID", (p.gdacs_event_id as string) || (p.usgs_id as string) || null],
      ]
        .filter(([, v]) => v)
        .map(([k, v]) => (
          <div key={k as string} className="contents">
            <dt className="text-neutral-500">{k}</dt>
            <dd className="truncate text-neutral-200">{v as string}</dd>
          </div>
        ))}
    </dl>
  </>
)}
```
(If `p` is not already in scope at that point in the component, add `const p = event.payload as Record<string, unknown>` near the top of the component body.)

- [ ] **Step 3: Verify tsc + lint**

Run: `cd osint-frontend && npx tsc --noEmit && npx eslint components/EventDetailCard.tsx`
Expected: no errors.

- [ ] **Step 4: Visual check**

With dev server up, click a quake / fire marker → panel shows the 0–3 gauge with the marker in the right band + metadata rows. (Headless: reuse `shot-live.mjs`, or verify manually in browser.)

- [ ] **Step 5: Commit**

```bash
git add osint-frontend/components/EventDetailCard.tsx
git commit -m "feat(map): GDACS-style 0-3 score gauge + hazard metadata in detail panel"
```

---

### Task 6: Full verification + PR update

**Files:** none (verification only)

- [ ] **Step 1: Full frontend gate**

Run:
```bash
cd osint-frontend && npx tsc --noEmit && npx eslint . && pnpm test
```
Expected: tsc clean; eslint 0 errors; all vitest pass (footprints + hazardSymbols + markers + existing).

- [ ] **Step 2: End-to-end visual proof**

With the full stack up (postgres/redis/worker/beat/api on :8000 + `pnpm dev` on :3000), run `scratch/pw/shot-live.mjs` and `shot-relief.mjs`. Confirm: per-type icons (quake/fire), footprints reveal on zoom-in, no glow rings, detail panel gauge. Save screenshots to scratchpad.

- [ ] **Step 3: Push and refresh PR #204 body**

```bash
git push origin fix/map-terrain-hillshade
gh pr edit 204 --body "..."  # note the new markers/footprints/gauge alongside the topo basemap
```
Do NOT merge — Basil merges.

---

## Self-Review

**Spec coverage:**
- Per-type symbols → Task 2 (`hazardIcon`) + Task 3 (pin render). ✓
- Color by alert → Task 2 (`hazardColor`). ✓
- Remove glow ring → Task 3. ✓
- Synthesized footprints (quake contours, fire circle, TC/FL/VO extent) → Task 1 + 2 (`footprintFeatures`). ✓
- Zoom-reveal → Task 4 (`minzoom` + opacity interpolate). ✓
- Detail panel + 0–3 gauge + metadata → Task 5. ✓
- FIRMS untouched → only hazard/weather category events get footprints; FIRMS point-fires keep their dot (Task 3 keeps non-icon dot path for clusterable/other). Note: `nasa-firms` maps to WF kind → would get a flame icon. **Decision:** FIRMS events are category `weather` with no `severity_raw` ha, so `footprintFeatures` returns the severity extent circle and they DO get a flame pin. If that's too noisy, gate the icon to `ev.source !== "nasa-firms"` — flag to user during review.
- Testing → Tasks 1,2 (vitest), 4,5 (screenshots). ✓

**Placeholder scan:** none — all steps carry real code/commands.

**Type consistency:** `footprintFeatures` returns `GeoJSON.Feature[]`; consumed in Task 4 into a `FeatureCollection`. `MarkerStyle` loses `ring` in Task 3 and no later task references `ring`. `HazardIcon`/`HazardKind` names consistent across Tasks 2–3.

**Open item for user:** FIRMS (54k point-fires) → flame icon may be too busy. Default keeps them as flame pins with no footprint unless they carry ha; can suppress to plain dot on request.
