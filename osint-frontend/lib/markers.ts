import { colorForEvent, sourceKeyForEvent, type EventRow } from "./types"

export type MarkerShape = "circle" | "diamond" | "dot"

export interface MarkerStyle {
  shape: MarkerShape
  size: number
  color: string
  /** Draw an emphasis ring so the marker stands out (notable earthquakes). */
  ring: boolean
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}

/** Magnitude at/above which a quake earns an emphasis ring on the map. */
const EQ_RING_MIN_MAG = 4.5

/** Should this earthquake be visually emphasised so the user can't miss it?
 *
 * USGS quakes ring at M4.5+. GDACS only lists significant quakes, so an
 * orange/red alert always rings; a green one falls back to the magnitude
 * gate. Non-earthquake events never ring.
 */
function isNotableQuake(
  sk: ReturnType<typeof sourceKeyForEvent>,
  payload: Record<string, unknown>,
): boolean {
  if (sk === "USGS") {
    return Number(payload.magnitude ?? 0) >= EQ_RING_MIN_MAG
  }
  if (sk === "GDACS") {
    if (String(payload.event_type ?? "").toUpperCase() !== "EQ") return false
    const alert = String(payload.alert_level ?? "").toLowerCase()
    if (alert === "orange" || alert === "red") return true
    return Number(payload.magnitude ?? 0) >= EQ_RING_MIN_MAG
  }
  return false
}

/** Geometry of a flat-map marker, derived from the event source + payload. */
export function markerStyle(ev: EventRow): MarkerStyle {
  const color = colorForEvent(ev)
  const sk = sourceKeyForEvent(ev)
  const payload = ev.payload as Record<string, unknown>
  const ring = isNotableQuake(sk, payload)

  switch (sk) {
    case "USGS": {
      const mag = Number(payload.magnitude ?? 0)
      return { shape: "circle", size: clamp(mag * 2, 4, 16), color, ring }
    }
    case "GDACS": {
      const level = String(payload.alert_level ?? "").toLowerCase()
      const map: Record<string, number> = { green: 8, orange: 12, red: 16 }
      return { shape: "diamond", size: map[level] ?? 10, color, ring }
    }
    case "FIRMS":
      return { shape: "dot", size: 5, color, ring }
    case "EONET":
      return { shape: "diamond", size: 9, color, ring }
    case "GDELT": {
      const mentions = Number(payload.num_mentions ?? 0)
      return { shape: "circle", size: clamp(mentions / 50, 3, 10), color, ring }
    }
    case "yfinance":
      return { shape: "circle", size: 7, color, ring }
    default:
      // Category-based fallback for new sources (opensky-adsb, abuse-ch,
      // polymarket, etc.) that don't have a SourceKey yet.
      if (ev.source === "opensky-adsb" || ev.category === "tracking") {
        return { shape: "diamond", size: 4, color, ring }
      }
      if (ev.source.startsWith("abuse-ch-") || ev.category === "cyber") {
        return { shape: "diamond", size: 6, color, ring }
      }
      if (ev.source === "polymarket" || ev.category === "market") {
        return { shape: "circle", size: 6, color, ring }
      }
      return { shape: "circle", size: 6, color, ring }
  }
}

/** Globe point altitude from severity (0 .. 0.5 radius units). */
export function pointAltitude(severity: number): number {
  return clamp(severity, 0, 1) * 0.5
}
