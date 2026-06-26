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
  const src = (ev.source ?? "").toLowerCase()
  if (src.includes("usgs")) {
    const mag = Number(payload(ev).magnitude ?? 0)
    if (mag >= 6) return RED
    if (mag >= 4.5) return ORANGE
  }
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
