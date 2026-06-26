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

export type SourceKey = "GDELT" | "USGS" | "GDACS" | "FIRMS" | "yfinance" | "EONET" | "NEWS"

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
  score_name: string
  score_value: number
  components: ScoreComponents | null
  method_version: string | null
}

export interface IngestHealthRow {
  source: string
  day: string
  success_n: number | null
  failure_n: number | null
  last_success: string | null
  last_failure: string | null
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
  { key: "EONET", label: "Natural events (NASA)", category: "hazard", color: "rgb(217,70,239)", hex: "#d946ef", pane: "map" },
  { key: "NEWS", label: "News (RSS)", category: "news", color: "rgb(56,189,248)", hex: "#38bdf8", pane: "map" },
]

/** Source filters scoped to a single pane. */
export function sourceFiltersForPane(pane: Pane): SourceFilterDef[] {
  return SOURCE_FILTERS.filter((f) => f.pane === pane)
}

/** GDACS / USGS / EONET all carry the "hazard" category but lump many distinct
 *  disasters together. These are the source keys whose events are filtered by
 *  disaster TYPE instead of by source, so the rail can offer "hide volcanoes"
 *  rather than one giant "multi-hazard" switch. */
export const HAZARD_SOURCE_KEYS: SourceKey[] = ["USGS", "GDACS", "EONET"]

/** Disaster-type filter keys (mirror HazardKind, minus "other"). */
export type HazardTypeKey = "EQ" | "TC" | "FL" | "VO" | "DR" | "WF"

export interface HazardTypeDef {
  key: HazardTypeKey
  label: string
  hex: string
}

/** The per-type disaster filters shown on the map rail, each with a distinct
 *  colour so the legend reads at a glance. */
export const HAZARD_TYPE_FILTERS: HazardTypeDef[] = [
  { key: "EQ", label: "Earthquakes", hex: "#ef4444" },
  { key: "TC", label: "Cyclones", hex: "#f97316" },
  { key: "FL", label: "Floods", hex: "#38bdf8" },
  { key: "WF", label: "Wildfires", hex: "#eab308" },
  { key: "VO", label: "Volcanoes", hex: "#d946ef" },
  { key: "DR", label: "Droughts", hex: "#a16207" },
]

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
  if (src.startsWith("RSS-") || ev.category === "news") return "#38bdf8"
  if (src.includes("USGS")) return "#ef4444"
  if (src.includes("GDACS")) return "#f97316"
  if (src === "EONET" || src.includes("EONET")) return "#d946ef"
  if (src.includes("FIRMS")) return "#eab308"
  if (src.includes("YF") || src.includes("YFINANCE") || ev.category === "market") return "#22c55e"
  if (src.includes("GDELT") || ev.category === "geopolitical") return "#a3a3a3"
  if (src.includes("OPENSKY") || src.includes("ADSB") || ev.category === "tracking") {
    return "#06b6d4" // cyan-500 — distinct from news (#38bdf8 sky-400)
  }
  if (src.includes("ABUSE") || ev.category === "cyber") return "#a855f7" // violet-500
  if (src === "POLYMARKET") return "#10b981" // emerald-500
  // category fallback
  switch (ev.category) {
    case "hazard":
      return "#ef4444"
    case "weather":
      return "#eab308"
    case "market":
      return "#22c55e"
    case "tracking":
      return "#06b6d4"
    case "cyber":
      return "#a855f7"
    default:
      return "#a3a3a3"
  }
}

/** Which SourceKey does an event belong to (for toggle filtering). */
export function sourceKeyForEvent(ev: EventRow): SourceKey | null {
  const src = (ev.source || "").toUpperCase()
  if (src.startsWith("RSS-")) return "NEWS"
  if (src.includes("USGS")) return "USGS"
  if (src.includes("GDACS")) return "GDACS"
  if (src === "EONET") return "EONET"
  if (src.includes("FIRMS")) return "FIRMS"
  if (src.includes("YF") || src.includes("YFINANCE")) return "yfinance"
  if (src.includes("GDELT")) return "GDELT"
  // fall back on category
  switch (ev.category) {
    case "news":
      return "NEWS"
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
