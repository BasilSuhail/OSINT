// One source of truth: event -> { kind, color, icon, footprint }. Drives both the
// map pin (icon + colour) and the synthesized footprint layer.
import type { EventRow } from "./types"
import { circlePolygon, fireRadiusKm, parseBurnedHa, quakeBands } from "./footprints"

/** Minimal GeoJSON feature for footprints (avoids a @types/geojson dependency —
 *  mirrors the local types in lib/geo.ts). Geometry is loose so it carries both
 *  synthesized circles (Polygon) and real upstream geometry passed straight
 *  through (MultiLineString MMI contours, Polygon/MultiPolygon burn scars). */
export interface HazardFeature {
  type: "Feature"
  properties: { color: string; fillOpacity: number }
  geometry: { type: string; coordinates: unknown }
}

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
  // EONET has no event_type code — infer the kind from the title so its
  // storms / volcanoes get the right symbol instead of a plain dot.
  const title = String(payload(ev).title ?? "").toLowerCase()
  if (/storm|typhoon|cyclone|hurricane/.test(title)) return "TC"
  if (title.includes("volcano")) return "VO"
  if (title.includes("flood")) return "FL"
  if (title.includes("wildfire") || title.includes("fire")) return "WF"
  return "other"
}

export function hazardColor(ev: EventRow): string {
  // Earthquakes are coloured by magnitude across BOTH sources (USGS + GDACS) so
  // the same quake never reads orange from one feed and red from another — the
  // colour was inconsistent because USGS used magnitude while GDACS used its
  // alert level. M>=6 red, M>=4.5 orange, else green.
  if (hazardKind(ev) === "EQ") {
    const mag = Number(payload(ev).magnitude ?? 0)
    if (mag >= 6) return RED
    if (mag >= 4.5) return ORANGE
    return GREEN
  }
  // Non-quake hazards: colour by the GDACS alert level.
  const alert = String(payload(ev).alert_level ?? "").toLowerCase()
  if (alert === "red") return RED
  if (alert === "orange") return ORANGE
  if (alert === "green") return GREEN
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

function poly(ring: [number, number][], color: string, fillOpacity: number): HazardFeature {
  return {
    type: "Feature",
    properties: { color, fillOpacity },
    geometry: { type: "Polygon", coordinates: [ring] },
  }
}

/** Real footprint geometry stashed on the payload by the backend enrichment
 *  (issue #205): USGS ShakeMap MMI contours / GDACS burn-flood polygons. Passed
 *  straight through to the map layers with the colour the backend tagged. */
function realFootprintFeatures(p: Record<string, unknown>): HazardFeature[] | null {
  const fc = p.footprint_geojson as
    | { features?: Array<{ geometry?: { type?: string; coordinates?: unknown }; properties?: Record<string, unknown> }> }
    | undefined
  if (!fc || !Array.isArray(fc.features) || fc.features.length === 0) return null
  const out: HazardFeature[] = []
  for (const f of fc.features) {
    const geom = f.geometry
    if (!geom || typeof geom.type !== "string" || geom.coordinates == null) continue
    const props = f.properties ?? {}
    const color = typeof props.color === "string" ? props.color : ORANGE
    const fillOpacity = typeof props.fillOpacity === "number" ? props.fillOpacity : 0.2
    out.push({
      type: "Feature",
      properties: { color, fillOpacity },
      geometry: { type: geom.type, coordinates: geom.coordinates },
    })
  }
  return out.length > 0 ? out : null
}

/** Footprint polygons for an event. Prefers the real upstream geometry when the
 *  backend has enriched it; otherwise falls back to a synthesized circle (largest
 *  first so smaller, hotter rings paint on top). Empty when the event has no
 *  coordinates or no usable size. */
export function footprintFeatures(ev: EventRow): HazardFeature[] {
  const p = payload(ev)
  const real = realFootprintFeatures(p)
  if (real) return real

  const lon = ev.lon
  const lat = ev.lat
  if (lon == null || lat == null) return []
  const kind = hazardKind(ev)

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
