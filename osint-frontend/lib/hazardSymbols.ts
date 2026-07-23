// One source of truth: event -> { kind, color, icon, footprint }. Drives both the
// map pin (icon + colour) and the synthesized footprint layer.
import type { EventRow } from "./types"
import { circlePolygon, fireRadiusKm, magnitudeAreaHa, parseBurnedHa, quakeBands } from "./footprints"

/** Minimal GeoJSON feature for footprints (avoids a @types/geojson dependency —
 *  mirrors the local types in lib/geo.ts). Geometry is loose so it carries both
 *  synthesized circles (Polygon) and real upstream geometry passed straight
 *  through (MultiLineString MMI contours, Polygon/MultiPolygon burn scars). */
export interface HazardFeature {
  type: "Feature"
  properties: { color: string; fillOpacity: number }
  geometry: { type: string; coordinates: unknown }
}

export type HazardKind = "EQ" | "WF" | "TC" | "FL" | "VO" | "DR" | "ICE" | "other"
export type HazardIcon = "activity" | "flame" | "wind" | "droplets" | "triangle" | "sun" | "snowflake" | "dot"

const GREEN = "#22c55e"
const ORANGE = "#f97316"
const RED = "#ef4444"
const ICE = "#67e8f9"

function payload(ev: EventRow): Record<string, unknown> {
  return (ev.payload ?? {}) as Record<string, unknown>
}

export function hazardKind(ev: EventRow): HazardKind {
  const src = (ev.source ?? "").toLowerCase()
  if (src.includes("usgs")) return "EQ"
  if (src.includes("firms")) return "WF"
  const t = String(payload(ev).event_type ?? "").toUpperCase()
  if (t === "EQ" || t === "WF" || t === "TC" || t === "FL" || t === "VO" || t === "DR" || t === "ICE") return t
  const categories = Array.isArray(payload(ev).categories)
    ? (payload(ev).categories as unknown[]).map((c) => String(c).toLowerCase())
    : []
  if (categories.some((c) => /ice|snow/.test(c))) return "ICE"
  // EONET has no event_type code — infer the kind from the title so its
  // storms / volcanoes get the right symbol instead of a plain dot.
  const title = String(payload(ev).title ?? "").toLowerCase()
  if (/storm|typhoon|cyclone|hurricane/.test(title)) return "TC"
  if (title.includes("volcano")) return "VO"
  if (title.includes("flood")) return "FL"
  if (title.includes("drought")) return "DR"
  if (title.includes("wildfire") || title.includes("fire")) return "WF"
  if (/ice|iceberg|snow|glacier/.test(title)) return "ICE"
  return "other"
}

export function hazardColor(ev: EventRow): string {
  if (hazardKind(ev) === "ICE") return ICE
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
    case "DR": return "sun"
    case "ICE": return "snowflake"
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
const LINE_TYPES = new Set(["LineString", "MultiLineString"])

function realFootprintFeatures(
  p: Record<string, unknown>,
  kind: HazardKind,
  expanded: boolean,
): HazardFeature[] | null {
  const fc = p.footprint_geojson as
    | { features?: Array<{ geometry?: { type?: string; coordinates?: unknown }; properties?: Record<string, unknown> }> }
    | undefined
  if (!fc || !Array.isArray(fc.features) || fc.features.length === 0) return null
  const out: HazardFeature[] = []
  for (const f of fc.features) {
    const geom = f.geometry
    if (!geom || typeof geom.type !== "string" || geom.coordinates == null) continue
    // Cyclones collapse to their track line when not selected — the
    // wind-probability cones span thousands of km and crowd the whole map.
    // Clicking the storm expands it to the full footprint (cones + track).
    if (kind === "TC" && !expanded && !LINE_TYPES.has(geom.type)) continue
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
/** Modest wind-extent radius (km) for a cyclone's current position. From the
 *  reported wind speed (kts — EONET `magnitude_value`, GDACS `magnitude`) when
 *  present, else the severity. Capped so it reads as the storm's reach without
 *  recreating the old overlapping-cone soup. */
function cycloneWindRadiusKm(p: Record<string, unknown>, severity: unknown): number {
  const kts = Number(p.magnitude_value ?? p.magnitude ?? 0)
  if (kts > 0) return Math.max(120, Math.min(500, kts * 6))
  return severityRadiusKm(Number(severity ?? 0))
}

/** Area an event reports about itself, in hectares. EONET is the only source
 *  that does this — a wildfire in acres, sea ice in square nautical miles — and
 *  it ships single-Point geometry, so without this its fires drew nothing at
 *  all (#612). */
function reportedAreaHa(p: Record<string, unknown>): number | null {
  return magnitudeAreaHa(
    typeof p.magnitude_value === "number" ? p.magnitude_value : null,
    typeof p.magnitude_unit === "string" ? p.magnitude_unit : null,
  )
}

export function footprintFeatures(ev: EventRow, expanded = false): HazardFeature[] {
  const p = payload(ev)
  const kind = hazardKind(ev)
  const real = realFootprintFeatures(p, kind, expanded)

  const lon = ev.lon
  const lat = ev.lat

  // Cyclones: show the real geometry (track always; full wind cones once the
  // storm is clicked/expanded). Add the synthesized wind-extent circle ONLY when
  // there is no real wind area to show — i.e. an EONET track-only storm, or the
  // collapsed default — so a clicked GDACS cyclone reveals its real cones
  // instead of a fat circle drawn on top of them.
  if (kind === "TC") {
    const out: HazardFeature[] = real ? [...real] : []
    const hasRealArea = out.some(
      (f) => f.geometry.type === "Polygon" || f.geometry.type === "MultiPolygon",
    )
    if (!hasRealArea && lon != null && lat != null) {
      out.push(poly(circlePolygon(lon, lat, cycloneWindRadiusKm(p, ev.severity)), hazardColor(ev), 0.12))
    }
    return out
  }

  if (real) return real
  if (lon == null || lat == null) return []

  if (kind === "EQ") {
    const mag = Number(p.magnitude ?? 0)
    const depth = Number(p.depth_km ?? 10) || 10
    if (mag <= 0) return []
    return quakeBands(mag, depth).map((b) =>
      poly(circlePolygon(lon, lat, b.radiusKm), b.color, 0.12),
    )
  }

  if (kind === "WF") {
    const ha = parseBurnedHa(typeof p.severity_raw === "string" ? p.severity_raw : null) ?? reportedAreaHa(p)
    if (!ha) return []
    return [poly(circlePolygon(lon, lat, fireRadiusKm(ha)), hazardColor(ev), 0.25)]
  }

  // TC / FL / VO / other: the reported extent when there is one (EONET sea ice
  // ships square nautical miles), else a severity-sized circle.
  const areaHa = reportedAreaHa(p)
  const r = areaHa ? fireRadiusKm(areaHa) : severityRadiusKm(Number(ev.severity ?? 0))
  return [poly(circlePolygon(lon, lat, r), hazardColor(ev), 0.15)]
}
