import { colorForEvent, sourceKeyForEvent, type EventRow } from "./types"

export type MarkerShape = "circle" | "diamond" | "dot"

export interface MarkerStyle {
  shape: MarkerShape
  size: number
  color: string
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}

/** Geometry of a flat-map marker, derived from the event source + payload. */
export function markerStyle(ev: EventRow): MarkerStyle {
  const color = colorForEvent(ev)
  const sk = sourceKeyForEvent(ev)
  const payload = ev.payload as Record<string, unknown>

  switch (sk) {
    case "USGS": {
      const mag = Number(payload.magnitude ?? 0)
      return { shape: "circle", size: clamp(mag * 2, 4, 16), color }
    }
    case "GDACS": {
      const level = String(payload.alert_level ?? "").toLowerCase()
      const map: Record<string, number> = { green: 8, orange: 12, red: 16 }
      return { shape: "diamond", size: map[level] ?? 10, color }
    }
    case "FIRMS":
      return { shape: "dot", size: 5, color }
    case "GDELT": {
      const mentions = Number(payload.num_mentions ?? 0)
      return { shape: "circle", size: clamp(mentions / 50, 3, 10), color }
    }
    case "yfinance":
      return { shape: "circle", size: 7, color }
    default:
      return { shape: "circle", size: 6, color }
  }
}

/** Globe point altitude from severity (0 .. 0.5 radius units). */
export function pointAltitude(severity: number): number {
  return clamp(severity, 0, 1) * 0.5
}
