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

  // Sizes trimmed ~15% for a lighter, less cluttered map (#252).
  switch (sk) {
    case "USGS": {
      const mag = Number(payload.magnitude ?? 0)
      return { shape: "circle", size: clamp(mag * 1.7, 3, 13), color }
    }
    case "GDACS": {
      const level = String(payload.alert_level ?? "").toLowerCase()
      const map: Record<string, number> = { green: 7, orange: 10, red: 13 }
      return { shape: "diamond", size: map[level] ?? 8, color }
    }
    case "EONET":
      return { shape: "diamond", size: 8, color }
    case "GDELT": {
      const mentions = Number(payload.num_mentions ?? 0)
      return { shape: "circle", size: clamp(mentions / 50, 3, 8), color }
    }
    case "yfinance":
      return { shape: "circle", size: 6, color }
    default:
      // Category-based fallback for new sources (opensky-adsb, abuse-ch,
      // polymarket, etc.) that don't have a SourceKey yet.
      if (ev.source === "opensky-adsb" || ev.category === "tracking") {
        return { shape: "diamond", size: 4, color }
      }
      if (ev.source.startsWith("abuse-ch-") || ev.category === "cyber") {
        return { shape: "diamond", size: 5, color }
      }
      if (ev.source === "polymarket" || ev.category === "market") {
        return { shape: "circle", size: 5, color }
      }
      return { shape: "circle", size: 5, color }
  }
}

