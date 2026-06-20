export type Category =
  | "market"
  | "geopolitical"
  | "hazard"
  | "weather"
  | "tracking"
  | "space"
  | "news"
  | "cyber"
  | "mesh"

export type SourceKey = "GDELT" | "USGS" | "GDACS" | "FIRMS" | "yfinance" | "EONET"

export interface GdeltPayload {
  goldstein?: number
  num_mentions?: number
  avg_tone?: number
  source_url?: string
  event_root_code?: string
}

export interface UsgsPayload {
  place?: string
  magnitude?: number
  alert?: string | null
  depth_km?: number
}

export interface GdacsPayload {
  event_type?: string
  alert_level?: string
  country_name?: string
  severity_raw?: number
  link?: string
}

export interface FirmsPayload {
  brightness?: number
  frp?: number
  daynight?: string
}

export interface YfinancePayload {
  ticker?: string
  close?: number
  drawdown_pct?: number
}

export type EventPayload =
  | GdeltPayload
  | UsgsPayload
  | GdacsPayload
  | FirmsPayload
  | YfinancePayload
  | Record<string, unknown>

export interface EventRow {
  id: string
  source: string
  source_event_id: string | null
  occurred_at: string
  fetched_at: string | null
  category: Category | string
  severity: number
  keywords: string[] | null
  country: string | null
  lat: number | null
  lon: number | null
  payload: EventPayload
}

export interface ScoreComponents {
  z?: {
    market?: number
    geopolitical?: number
    hazard?: number
    [key: string]: number | undefined
  }
  [key: string]: unknown
}

export interface ScoreRow {
  country: string
  bucket_start: string
  bucket_length: string | number
  score_name: string
  score_value: number
  components: ScoreComponents | null
  method_version: string | null
}

/** Which pane a source renders on. NASA / satellite-derived feeds belong on
 *  the globe; everything else (geopolitical, markets, ground-sensor hazards,
 *  news) belongs on the flat map. Keeps the two panes from duplicating. */
export type Pane = "map" | "globe"

/** The five toggleable source filters, mapped to a category + colour + pane. */
export interface SourceFilterDef {
  key: SourceKey
  label: string
  /** category used to match EventRow.category */
  category: Category
  color: string
  /** maplibre-friendly hex */
  hex: string
  /** which pane this source renders on */
  pane: Pane
}

export const SOURCE_FILTERS: SourceFilterDef[] = [
  { key: "GDELT", label: "Geopolitical events", category: "geopolitical", color: "rgb(163,163,163)", hex: "#a3a3a3", pane: "map" },
  { key: "yfinance", label: "Markets", category: "market", color: "rgb(34,197,94)", hex: "#22c55e", pane: "map" },
  { key: "USGS", label: "Earthquakes", category: "hazard", color: "rgb(239,68,68)", hex: "#ef4444", pane: "map" },
  { key: "GDACS", label: "Multi-hazard alerts", category: "hazard", color: "rgb(249,115,22)", hex: "#f97316", pane: "map" },
  { key: "FIRMS", label: "Active fires (satellite)", category: "weather", color: "rgb(234,179,8)", hex: "#eab308", pane: "globe" },
  { key: "EONET", label: "Natural events (NASA)", category: "hazard", color: "rgb(217,70,239)", hex: "#d946ef", pane: "globe" },
]

/** Source filters scoped to a single pane. */
export function sourceFiltersForPane(pane: Pane): SourceFilterDef[] {
  return SOURCE_FILTERS.filter((f) => f.pane === pane)
}

/** Which pane should render this event. Returns null if the source is unknown. */
export function paneForEvent(ev: EventRow): Pane | null {
  const sk = sourceKeyForEvent(ev)
  if (!sk) return null
  const def = SOURCE_FILTERS.find((f) => f.key === sk)
  return def?.pane ?? null
}

/** Resolve a marker colour from an event's source / category. */
export function colorForEvent(ev: EventRow): string {
  const src = (ev.source || "").toUpperCase()
  if (src.includes("USGS")) return "#ef4444"
  if (src.includes("GDACS")) return "#f97316"
  if (src === "EONET" || src.includes("EONET")) return "#d946ef"
  if (src.includes("FIRMS")) return "#eab308"
  if (src.includes("YF") || src.includes("YFINANCE") || ev.category === "market") return "#22c55e"
  if (src.includes("GDELT") || ev.category === "geopolitical") return "#a3a3a3"
  // category fallback
  switch (ev.category) {
    case "hazard":
      return "#ef4444"
    case "weather":
      return "#eab308"
    case "market":
      return "#22c55e"
    default:
      return "#a3a3a3"
  }
}

/** Which SourceKey does an event belong to (for toggle filtering). */
export function sourceKeyForEvent(ev: EventRow): SourceKey | null {
  const src = (ev.source || "").toUpperCase()
  if (src.includes("USGS")) return "USGS"
  if (src.includes("GDACS")) return "GDACS"
  if (src === "EONET") return "EONET"
  if (src.includes("FIRMS")) return "FIRMS"
  if (src.includes("YF") || src.includes("YFINANCE")) return "yfinance"
  if (src.includes("GDELT")) return "GDELT"
  // fall back on category
  switch (ev.category) {
    case "market":
      return "yfinance"
    case "geopolitical":
      return "GDELT"
    case "weather":
      return "FIRMS"
    case "hazard":
      return "GDACS"
    default:
      return null
  }
}

/** Country stress colour scale used for polygon shading. */
export function countryFillColor(score: number): string {
  if (score >= 0.8) return "rgba(239,68,68,0.30)"
  if (score >= 0.6) return "rgba(249,115,22,0.24)"
  if (score >= 0.4) return "rgba(234,179,8,0.18)"
  return "rgba(34,197,94,0.12)"
}

export function scoreTextColor(score: number): string {
  if (score >= 0.8) return "#ef4444"
  if (score >= 0.6) return "#f97316"
  if (score >= 0.4) return "#eab308"
  return "#22c55e"
}
