"use client"

import { useEffect, useMemo, useState } from "react"
import { format, subDays } from "date-fns"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { useEvents } from "@/app/providers"
import { getSupabase } from "@/lib/supabase"
import type { EventRow, ScoreRow } from "@/lib/types"

const COMPOSITE_BUCKETS = 30

/** Global time-range picker options. The dashboard reads its panels off
 *  the chosen window so every chart / list scopes to the same period. */
const WINDOW_OPTIONS = [
  { key: "24h", label: "24 h", ms: 24 * 60 * 60 * 1000, days: 1 },
  { key: "7d", label: "7 d", ms: 7 * 24 * 60 * 60 * 1000, days: 7 },
  { key: "30d", label: "30 d", ms: 30 * 24 * 60 * 60 * 1000, days: 30 },
] as const
type WindowKey = (typeof WINDOW_OPTIONS)[number]["key"]


const regionNames =
  typeof Intl !== "undefined" && "DisplayNames" in Intl
    ? new Intl.DisplayNames(["en"], { type: "region" })
    : null

function countryName(iso: string): string {
  try {
    return regionNames?.of(iso) ?? iso
  } catch {
    return iso
  }
}

function countryFlagEmoji(iso: string): string {
  if (!iso || iso.length !== 2) return ""
  const codePoints = iso
    .toUpperCase()
    .split("")
    .map((c) => 127397 + c.charCodeAt(0))
  return String.fromCodePoint(...codePoints)
}

function severityBarColor(s: number): string {
  if (s >= 0.8) return "#ef4444"
  if (s >= 0.6) return "#f97316"
  if (s >= 0.4) return "#eab308"
  return "#22c55e"
}

/** VADER compound ∈ [-1, 1] → bar colour. Negative = rose, positive =
 *  emerald, neutral = neutral. Mirrors the chip-colour cut-offs used by
 *  NIP's GPR gauge so a Bloomberg-terminal-style red/green reading lands.
 *  Returns null when payload.sentiment is missing (pre-enrichment rows)
 *  so the renderer can fall back to severity. */
function sentimentBarColor(compound: number): string {
  if (compound <= -0.5) return "#e11d48"
  if (compound <= -0.05) return "#f43f5e"
  if (compound >= 0.5) return "#10b981"
  if (compound >= 0.05) return "#34d399"
  return "#737373"
}

function bestTitle(ev: EventRow): string {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const candidates = [p?.title, p?.headline, p?.place, p?.country_name]
  for (const c of candidates) if (typeof c === "string" && c.trim()) return c
  return `${ev.source} event`
}

function bestSummary(ev: EventRow): string | null {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const candidates = [p?.summary, p?.description]
  for (const c of candidates) {
    if (typeof c === "string" && c.trim()) return c
  }
  return null
}

function newsSourceLabel(ev: EventRow): string {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const feed = typeof p?.feed_name === "string" ? p.feed_name : null
  if (feed) return feed
  // Strip the rss- prefix on the source slug for a tidy chip.
  return ev.source.replace(/^rss-/, "").replace(/-/g, " ")
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (!Number.isFinite(then)) return ""
  const diffSec = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (diffSec < 60) return `${diffSec}s`
  const m = Math.round(diffSec / 60)
  if (m < 60) return `${m}m`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h`
  const d = Math.round(h / 24)
  return `${d}d`
}

/** Editorial source weights for the impact ranking. Mirrors the NIP
 *  formula (BasilSuhail/news-intelligence-platform / 03-IMPACT-SCORE-ALGORITHM).
 *  Higher = more credibility / global reach. Out-of-table sources get 0.5. */
const NEWS_SOURCE_WEIGHTS: Record<string, number> = {
  "rss-bbc-world": 1.0,
  "rss-reuters-world": 1.0,
  "rss-bbc-uk": 0.95,
  "rss-guardian-world": 0.9,
  "rss-dawn": 0.85,
  "rss-geo-english": 0.7,
  "uk-police": 0.6,
}

function sourceWeightFor(ev: EventRow): number {
  return NEWS_SOURCE_WEIGHTS[ev.source] ?? 0.5
}

/** 24 h linear-decay recency in [0, 1]. Cut to 0 once a row is more than
 *  a day old — the news feed is meant to be fresh. */
function recencyFor(ev: EventRow): number {
  const t = new Date(ev.occurred_at).getTime()
  if (!Number.isFinite(t)) return 0
  const ageH = Math.max(0, (Date.now() - t) / 3_600_000)
  return Math.max(0, 1 - ageH / 24)
}

/** Impact score per NIP, minus cluster size (own follow-up issue).
 *  Falls back to the keyword-boosted severity when sentiment is missing
 *  so pre-#131 rows still rank meaningfully. */
function impactScoreFor(ev: EventRow): number {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const rawSentiment =
    typeof p?.sentiment === "number"
      ? Math.abs(p.sentiment as number)
      : typeof ev.severity === "number"
        ? Math.abs(ev.severity - 0.35) * 2 // map 0.35→0, 0.85→1
        : 0
  return 0.45 * rawSentiment + 0.30 * recencyFor(ev) + 0.25 * sourceWeightFor(ev)
}

const NEWS_FILTERS: { key: string; label: string; match: (ev: EventRow) => boolean }[] = [
  { key: "all", label: "All", match: () => true },
  { key: "uk", label: "UK", match: (ev) => ev.source === "rss-bbc-uk" || ev.country === "GB" },
  {
    key: "world",
    label: "World",
    match: (ev) =>
      ev.source === "rss-bbc-world" ||
      ev.source === "rss-reuters-world" ||
      ev.source === "rss-guardian-world",
  },
  {
    key: "pakistan",
    label: "Pakistan",
    match: (ev) => ev.source === "rss-dawn" || ev.source === "rss-geo-english" || ev.country === "PK",
  },
  { key: "crime", label: "Crime", match: (ev) => ev.source === "uk-police" },
]

function useScoreSeries(scoreName: string, days: number = COMPOSITE_BUCKETS): { day: string; score: number; n: number }[] {
  const [data, setData] = useState<ScoreRow[]>([])
  useEffect(() => {
    const supabase = getSupabase()
    if (!supabase) return
    const since = subDays(new Date(), days).toISOString()
    supabase
      .from("scores")
      .select("*")
      .eq("score_name", scoreName)
      .gte("bucket_start", since)
      .order("bucket_start", { ascending: true })
      .limit(5000)
      .then(({ data: rows, error }) => {
        if (!error && rows) setData(rows as ScoreRow[])
      })
  }, [scoreName, days])

  return useMemo(() => {
    const byDay = new Map<string, { sum: number; n: number }>()
    for (const r of data) {
      const day = (r.bucket_start ?? "").slice(0, 10)
      const bucket = byDay.get(day) ?? { sum: 0, n: 0 }
      bucket.sum += r.score_value ?? 0
      bucket.n += 1
      byDay.set(day, bucket)
    }
    return Array.from(byDay.entries())
      .map(([day, { sum, n }]) => ({
        day,
        score: n > 0 ? sum / n : 0,
        n,
      }))
      .sort((a, b) => (a.day < b.day ? -1 : 1))
  }, [data])
}

/** Expected cadence per source slug, in minutes. Lifted from the beat
 *  schedule in app/tasks.py — sources beyond this are flagged amber /
 *  red on the source latency panel (#144). */
const SOURCE_CADENCE_MIN: Record<string, number> = {
  yfinance: 5,
  fred: 24 * 60,
  gdelt: 15,
  "usgs-quake": 15,
  usgs: 15,
  gdacs: 15,
  "nasa-firms": 60,
  eonet: 30,
  "rss-bbc-world": 60,
  "rss-bbc-uk": 60,
  "rss-reuters-world": 60,
  "rss-dawn": 60,
  "rss-guardian-world": 60,
  "rss-geo-english": 60,
  "uk-police": 24 * 60,
}

interface IngestHealthRow {
  source: string
  day: string
  success_n: number | null
  failure_n: number | null
  last_success: string | null
  last_failure: string | null
}

interface SourceLatencyRow {
  source: string
  lastSuccess: string | null
  ageMin: number | null
  cadenceMin: number | null
  band: "ok" | "warn" | "stale"
  failure24h: number
}

function useSourceLatency(): SourceLatencyRow[] {
  const [rows, setRows] = useState<IngestHealthRow[]>([])
  useEffect(() => {
    const supabase = getSupabase()
    if (!supabase) return
    const since = subDays(new Date(), 7).toISOString().slice(0, 10)
    supabase
      .from("ingest_health")
      .select("*")
      .gte("day", since)
      .order("day", { ascending: false })
      .limit(2000)
      .then(({ data, error }) => {
        if (!error && data) setRows(data as IngestHealthRow[])
      })
  }, [])

  return useMemo(() => {
    const latest = new Map<string, IngestHealthRow>()
    for (const r of rows) {
      const existing = latest.get(r.source)
      if (!existing) {
        latest.set(r.source, r)
        continue
      }
      const a = new Date(r.last_success ?? r.day).getTime()
      const b = new Date(existing.last_success ?? existing.day).getTime()
      if (a > b) latest.set(r.source, r)
    }

    const failure24hBySource = new Map<string, number>()
    const cutoff = Date.now() - 24 * 60 * 60 * 1000
    for (const r of rows) {
      const t = new Date(r.day).getTime()
      if (!Number.isFinite(t) || t < cutoff) continue
      failure24hBySource.set(
        r.source,
        (failure24hBySource.get(r.source) ?? 0) + (r.failure_n ?? 0),
      )
    }

    const out: SourceLatencyRow[] = []
    for (const [source, h] of latest) {
      const cadence = SOURCE_CADENCE_MIN[source] ?? null
      const lastSuccess = h.last_success
      const ageMin = lastSuccess
        ? (Date.now() - new Date(lastSuccess).getTime()) / 60_000
        : null
      let band: SourceLatencyRow["band"] = "ok"
      if (ageMin != null && cadence != null) {
        if (ageMin > cadence * 3) band = "stale"
        else if (ageMin > cadence * 1.5) band = "warn"
      }
      out.push({
        source,
        lastSuccess,
        ageMin,
        cadenceMin: cadence,
        band,
        failure24h: failure24hBySource.get(source) ?? 0,
      })
    }
    return out.sort((a, b) => {
      const bandRank = { stale: 0, warn: 1, ok: 2 }
      if (a.band !== b.band) return bandRank[a.band] - bandRank[b.band]
      return (b.ageMin ?? 0) - (a.ageMin ?? 0)
    })
  }, [rows])
}

function ageLabel(min: number | null): string {
  if (min == null) return "—"
  if (min < 1) return "<1 m"
  if (min < 60) return `${Math.round(min)} m`
  const h = min / 60
  if (h < 24) return `${h.toFixed(1)} h`
  return `${(h / 24).toFixed(1)} d`
}

/** Latest CII row per country for the hero leaderboard tile (#139).
 *  Reads the most-recent ``score_name = cii_v1`` row per ISO directly
 *  from Supabase. Pure read; no aggregation here. */
function useLatestCiiByCountry(): Map<string, { iso: string; score: number }> {
  const [data, setData] = useState<ScoreRow[]>([])
  useEffect(() => {
    const supabase = getSupabase()
    if (!supabase) return
    const since = subDays(new Date(), 2).toISOString()
    supabase
      .from("scores")
      .select("*")
      .eq("score_name", "cii_v1")
      .gte("bucket_start", since)
      .order("bucket_start", { ascending: false })
      .limit(2000)
      .then(({ data: rows, error }) => {
        if (!error && rows) setData(rows as ScoreRow[])
      })
  }, [])

  return useMemo(() => {
    const latest = new Map<string, { iso: string; score: number }>()
    for (const r of data) {
      const iso = r.country
      if (!iso) continue
      if (latest.has(iso)) continue
      latest.set(iso, { iso, score: r.score_value ?? 0 })
    }
    return latest
  }, [data])
}

interface CiiCountryRow {
  iso: string
  current: number
  delta7d: number
  history: number[]
  unrest: number
  conflict: number
  security: number
  information: number
}

/** Per-country CII rows for the last 30 d, grouped + sorted by current
 *  score desc. Used by the leaderboard panel (#142). Reads cii_v1 rows
 *  directly from Supabase + breaks them out by ISO. */
function useCiiByCountry(): CiiCountryRow[] {
  const [rows, setRows] = useState<ScoreRow[]>([])
  useEffect(() => {
    const supabase = getSupabase()
    if (!supabase) return
    const since = subDays(new Date(), 30).toISOString()
    supabase
      .from("scores")
      .select("*")
      .eq("score_name", "cii_v1")
      .gte("bucket_start", since)
      .order("bucket_start", { ascending: true })
      .limit(20000)
      .then(({ data: result, error }) => {
        if (!error && result) setRows(result as ScoreRow[])
      })
  }, [])

  return useMemo(() => {
    const byIso = new Map<string, ScoreRow[]>()
    for (const r of rows) {
      if (!r.country) continue
      const arr = byIso.get(r.country) ?? []
      arr.push(r)
      byIso.set(r.country, arr)
    }
    const out: CiiCountryRow[] = []
    for (const [iso, arr] of byIso) {
      arr.sort((a, b) =>
        (a.bucket_start ?? "") < (b.bucket_start ?? "") ? -1 : 1,
      )
      const latest = arr.at(-1)
      const sevenDaysAgo = arr.find((r) => {
        const t = new Date(r.bucket_start ?? "").getTime()
        return Number.isFinite(t) && t >= Date.now() - 7 * 24 * 60 * 60 * 1000
      })
      const current = latest?.score_value ?? 0
      const prior = sevenDaysAgo?.score_value ?? current
      const components = (latest?.components ?? {}) as Record<string, number>
      out.push({
        iso,
        current,
        delta7d: current - prior,
        history: arr.map((r) => r.score_value ?? 0),
        unrest: components.unrest ?? 0,
        conflict: components.conflict ?? 0,
        security: components.security ?? 0,
        information: components.information ?? 0,
      })
    }
    return out.sort((a, b) => b.current - a.current)
  }, [rows])
}

/** Tiny inline sparkline (no chart lib). Draws a polyline + a single
 *  endpoint dot. Auto-scales to its parent width via SVG viewBox. */
function Sparkline({ values, color = "#22d3ee" }: { values: number[]; color?: string }) {
  if (values.length < 2) {
    return <span className="font-mono text-[10px] text-neutral-600">—</span>
  }
  const w = 80
  const h = 20
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const stepX = w / (values.length - 1)
  const points = values
    .map((v, i) => {
      const x = i * stepX
      const y = h - ((v - min) / range) * h
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(" ")
  const lastX = (values.length - 1) * stepX
  const lastY = h - ((values[values.length - 1] - min) / range) * h
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="shrink-0">
      <polyline points={points} fill="none" stroke={color} strokeWidth={1.5} />
      <circle cx={lastX} cy={lastY} r={2} fill={color} />
    </svg>
  )
}

function ciiBandColor(score: number): string {
  if (score >= 0.7) return "#ef4444"
  if (score >= 0.5) return "#f97316"
  if (score >= 0.3) return "#eab308"
  return "#22c55e"
}

/** Last N d CII series (mean across Tier-1 countries). N comes from the
 *  global window picker (#141). See docs/architecture/CII-METHODOLOGY.md. */
function useCiiSeries(days: number) {
  return useScoreSeries("cii_v1", days)
}

const KPI_ACCENT: Record<string, string> = {
  cyan: "border-l-cyan-700",
  rose: "border-l-rose-700",
  amber: "border-l-amber-700",
  emerald: "border-l-emerald-700",
}

function KpiTile({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string
  sub: string
  accent: keyof typeof KPI_ACCENT
}) {
  return (
    <div
      className={
        "rounded-md border border-neutral-800 bg-neutral-950 p-3 border-l-2 " +
        (KPI_ACCENT[accent] ?? "")
      }
    >
      <p className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">{label}</p>
      <p className="mt-1 truncate text-xl font-semibold tabular-nums text-neutral-100">{value}</p>
      <p className="mt-1 truncate font-mono text-[10px] text-neutral-500">{sub}</p>
    </div>
  )
}

interface DashboardSectionProps {
  configured: boolean
}

export function DashboardSection({ configured }: DashboardSectionProps) {
  const events = useEvents()
  const [windowKey, setWindowKey] = useState<WindowKey>("24h")
  const windowOpt = useMemo(
    () => WINDOW_OPTIONS.find((w) => w.key === windowKey) ?? WINDOW_OPTIONS[0],
    [windowKey],
  )
  const windowMs = windowOpt.ms
  const windowDays = windowOpt.days
  const windowLabel = windowOpt.label
  const ciiSeries = useCiiSeries(windowDays)
  const ciiByCountry = useLatestCiiByCountry()
  const ciiCountries = useCiiByCountry()
  const sourceLatency = useSourceLatency()

  /** Hero KPIs — pure reduces over the in-memory buffer + latest scores
   *  read. See #139 for the spec. */
  const heroKpis = useMemo(() => {
    const dayMs = 24 * 60 * 60 * 1000
    const now = Date.now()
    const cutoff = now - dayMs

    let events24h = 0
    const cellMap = new Map<string, Set<string>>()
    const sourcesSeen = new Set<string>()
    for (const ev of events) {
      const t = new Date(ev.occurred_at).getTime()
      if (!Number.isFinite(t)) continue
      if (t < cutoff) continue
      events24h += 1
      sourcesSeen.add(ev.source)
      if (ev.lat != null && ev.lon != null) {
        const key = `${Math.round(ev.lat)}_${Math.round(ev.lon)}`
        let set = cellMap.get(key)
        if (!set) {
          set = new Set()
          cellMap.set(key, set)
        }
        set.add((ev.category ?? "unknown").toLowerCase())
      }
    }
    let convergence24h = 0
    for (const cats of cellMap.values()) {
      if (cats.size >= 3) convergence24h += 1
    }

    let topIso: string | null = null
    let topScore = 0
    for (const c of ciiByCountry.values()) {
      if (c.score > topScore) {
        topScore = c.score
        topIso = c.iso
      }
    }

    // Sources expected = the union of every source slug ever seen in the
    // buffer (we only count what's been ingested historically). Healthy =
    // a source that has fired in the last 24 h. This is a buffer-based
    // approximation; the proper ingest_health read lives in #144.
    const sourcesEver = new Set<string>(events.map((e) => e.source))
    const sourcesTotal = sourcesEver.size
    const sourcesHealthy = sourcesSeen.size

    return {
      events24h,
      convergence24h,
      topCii: topIso ? { iso: topIso, score: topScore } : null,
      sourcesHealthy,
      sourcesTotal,
    }
  }, [events, ciiByCountry])

  /** News feed: latest RSS / police news rows. Map-side category=news.
   *  Also matches any source slug that starts with rss- or equals uk-police so
   *  we don't depend on the SourceKey enum. */
  const allNews = useMemo(() => {
    return events.filter((ev) => {
      const s = (ev.source ?? "").toLowerCase()
      return ev.category === "news" || s.startsWith("rss-") || s === "uk-police"
    })
  }, [events])

  const [newsFilter, setNewsFilter] = useState<string>("all")
  const [newsSort, setNewsSort] = useState<"impact" | "time">("impact")

  const filteredNews = useMemo(() => {
    const f = NEWS_FILTERS.find((x) => x.key === newsFilter) ?? NEWS_FILTERS[0]
    const matched = allNews.filter(f.match)
    if (newsSort === "impact") {
      return matched
        .map((ev) => ({ ev, score: impactScoreFor(ev) }))
        .sort((a, b) => b.score - a.score)
        .slice(0, 30)
        .map((x) => x.ev)
    }
    return matched.slice(0, 30)
  }, [allNews, newsFilter, newsSort])

  /** Severity histogram: events in last 24 h binned by severity into 10
   *  fixed-width buckets [0, 0.1) … [0.9, 1.0]. Drives the bar chart.
   *  Helps spot a hot tail (high-severity cluster) without scanning the
   *  whole map. Severity is the JRC-normalised stress score per event. */
  const severityBuckets = useMemo(() => {
    const BUCKETS = 10
    const counts = new Array<number>(BUCKETS).fill(0)
    const cutoff = Date.now() - windowMs
    for (const ev of events) {
      const t = new Date(ev.occurred_at).getTime()
      if (!Number.isFinite(t) || t < cutoff) continue
      const s = typeof ev.severity === "number" ? ev.severity : 0
      const idx = Math.min(BUCKETS - 1, Math.max(0, Math.floor(s * BUCKETS)))
      counts[idx] += 1
    }
    return counts.map((n, i) => {
      const lo = i / BUCKETS
      const hi = (i + 1) / BUCKETS
      return {
        bucket: `${lo.toFixed(1)}`,
        range: `${lo.toFixed(1)}–${hi.toFixed(1)}`,
        n,
        fill: severityBarColor((lo + hi) / 2),
      }
    })
  }, [events, windowMs])

  /** Geographic convergence detector — mirrors the WM algorithm cited in
   *  issue #128. For every event in the last 24 h, bucket lat/lon into a
   *  1°×1° cell. A cell where 3+ distinct event categories co-occur is an
   *  alert.
   *
   *  Score = 25 × categoryCount + min(25, eventCount × 2), capped at 100.
   *  Priority = "critical" when ≥ 4 categories OR score ≥ 90, else "high".
   *
   *  Pure reduce over the in-memory buffer — no new fetcher, no schema. */
  const convergenceAlerts = useMemo(() => {
    const cutoff = Date.now() - windowMs
    type Cell = {
      key: string
      lat: number
      lon: number
      categories: Set<string>
      events: typeof events
    }
    const cells = new Map<string, Cell>()
    for (const ev of events) {
      const t = new Date(ev.occurred_at).getTime()
      if (!Number.isFinite(t) || t < cutoff) continue
      if (ev.lat == null || ev.lon == null) continue
      const cellLat = Math.round(ev.lat)
      const cellLon = Math.round(ev.lon)
      const key = `${cellLat}_${cellLon}`
      let cell = cells.get(key)
      if (!cell) {
        cell = { key, lat: cellLat, lon: cellLon, categories: new Set(), events: [] }
        cells.set(key, cell)
      }
      cell.categories.add((ev.category ?? "unknown").toLowerCase())
      cell.events.push(ev)
    }
    const out: {
      key: string
      lat: number
      lon: number
      categories: string[]
      eventCount: number
      score: number
      priority: "critical" | "high"
    }[] = []
    for (const c of cells.values()) {
      if (c.categories.size < 3) continue
      const score = Math.min(100, 25 * c.categories.size + Math.min(25, c.events.length * 2))
      const priority: "critical" | "high" =
        c.categories.size >= 4 || score >= 90 ? "critical" : "high"
      out.push({
        key: c.key,
        lat: c.lat,
        lon: c.lon,
        categories: Array.from(c.categories).sort(),
        eventCount: c.events.length,
        score,
        priority,
      })
    }
    return out.sort((a, b) => b.score - a.score).slice(0, 12)
  }, [events, windowMs])

  /** Cyber-threat rollup (#177). Aggregates abuse.ch URLhaus + Feodo
   *  rows from the in-memory buffer over the chosen window. Surfaces
   *  the data shipped by #163 — counts per malware tag + a top-20
   *  list with status / severity. */
  const cyberThreats = useMemo(() => {
    const cutoff = Date.now() - windowMs
    const tagCounts = new Map<string, number>()
    const rows: { ev: EventRow; primary: string; status: string | null; severity: number }[] = []
    for (const ev of events) {
      if (ev.source !== "abuse-ch-urlhaus" && ev.source !== "abuse-ch-feodo") continue
      const t = new Date(ev.occurred_at).getTime()
      if (!Number.isFinite(t) || t < cutoff) continue
      const p = (ev.payload ?? {}) as Record<string, unknown>
      let primary: string
      let status: string | null = null
      if (ev.source === "abuse-ch-urlhaus") {
        const tags = Array.isArray(p.tags) ? (p.tags as string[]) : []
        primary = (tags[0] ?? (p.threat as string | null) ?? "url").toString()
        for (const t of tags) tagCounts.set(t, (tagCounts.get(t) ?? 0) + 1)
        status = (p.status as string | null) ?? null
      } else {
        primary = (p.malware as string | null) ?? "botnet"
        tagCounts.set(primary, (tagCounts.get(primary) ?? 0) + 1)
        status = (p.c2_status as string | null) ?? null
      }
      const sev = typeof ev.severity === "number" ? ev.severity : 0
      rows.push({ ev, primary, status, severity: sev })
    }
    const topTags = Array.from(tagCounts.entries())
      .map(([tag, n]) => ({ tag, n }))
      .sort((a, b) => b.n - a.n)
      .slice(0, 6)
    rows.sort((a, b) => {
      if (b.severity !== a.severity) return b.severity - a.severity
      return new Date(b.ev.occurred_at).getTime() - new Date(a.ev.occurred_at).getTime()
    })
    return { rows: rows.slice(0, 20), tagBreakdown: topTags, total: rows.length }
  }, [events, windowMs])

  /** Polymarket top-stress markets (#177 companion). Sorted by severity
   *  which is the "tail-event awareness" reading from #164. Surfaces
   *  the data so the market layer is visible. */
  const polyTopStress = useMemo(() => {
    const out: { ev: EventRow; price: number | null; question: string }[] = []
    for (const ev of events) {
      if (ev.source !== "polymarket") continue
      const p = (ev.payload ?? {}) as Record<string, unknown>
      const price = typeof p.yes_price === "number" ? (p.yes_price as number) : null
      const question = (p.question as string | null) ?? "—"
      out.push({ ev, price, question })
    }
    out.sort((a, b) => (b.ev.severity ?? 0) - (a.ev.severity ?? 0))
    return out.slice(0, 12)
  }, [events])

  if (!configured) return null

  return (
    <section
      aria-label="Dashboard charts"
      className="relative w-full bg-neutral-950 px-4 py-8 text-neutral-100 sm:px-6 lg:px-10"
    >
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
            Dashboard
          </h2>
          {/* Global time-range picker (#141). Every panel below scopes
           *  its memo to the chosen window so the page reads consistently. */}
          <div
            role="group"
            aria-label="Time range"
            className="inline-flex overflow-hidden rounded-md border border-neutral-800 font-mono text-[10px] uppercase tracking-wider"
          >
            {WINDOW_OPTIONS.map((opt) => (
              <button
                key={opt.key}
                type="button"
                onClick={() => setWindowKey(opt.key)}
                aria-pressed={windowKey === opt.key}
                className={
                  "px-2 py-0.5 transition-colors " +
                  (windowKey === opt.key
                    ? "bg-cyan-950/40 text-cyan-200"
                    : "bg-neutral-900/50 text-neutral-500 hover:text-neutral-300")
                }
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-600">
          {events.length.toLocaleString()} events in buffer · window {windowLabel}
        </span>
      </div>

      {/* Hero KPI row (#139). 4 stat tiles at the top of the dashboard
       *  so the user sees the system state before scrolling into the
       *  charts. Numbers come from in-memory buffer + latest CII rows. */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile
          label="Events · 24 h"
          value={heroKpis.events24h.toLocaleString()}
          sub={`${events.length.toLocaleString()} in buffer`}
          accent="cyan"
        />
        <KpiTile
          label="Top CII country"
          value={
            heroKpis.topCii
              ? `${countryFlagEmoji(heroKpis.topCii.iso)} ${heroKpis.topCii.iso}`
              : "—"
          }
          sub={
            heroKpis.topCii
              ? `score ${heroKpis.topCii.score.toFixed(3)} · ${countryName(heroKpis.topCii.iso)}`
              : "no CII rows yet"
          }
          accent="rose"
        />
        <KpiTile
          label="Convergence · 24 h"
          value={heroKpis.convergence24h.toString()}
          sub="cells with 3+ categories"
          accent="amber"
        />
        <KpiTile
          label="Source health"
          value={`${heroKpis.sourcesHealthy} / ${heroKpis.sourcesTotal}`}
          sub="active in last 24 h"
          accent="emerald"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-12">
        {/* CII v1 time series — mean across Tier-1 countries. See
         *  docs/architecture/CII-METHODOLOGY.md. */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-12">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
              CII v1 · mean across Tier-1, last {windowLabel}
            </h3>
            <span className="font-mono text-[10px] tabular-nums text-neutral-500">
              {ciiSeries.length} days
            </span>
          </div>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={ciiSeries} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="rgba(115,115,115,0.15)" strokeDasharray="4 4" />
                <XAxis
                  dataKey="day"
                  stroke="rgba(115,115,115,0.6)"
                  fontSize={10}
                  tickFormatter={(d) => format(new Date(d), "MMM d")}
                />
                <YAxis
                  stroke="rgba(115,115,115,0.6)"
                  fontSize={10}
                  domain={[0, 1]}
                  tickFormatter={(v) => v.toFixed(1)}
                />
                <Tooltip
                  contentStyle={{
                    background: "rgba(10,10,10,0.92)",
                    border: "1px solid rgba(82,82,82,0.6)",
                    fontFamily: "monospace",
                    fontSize: 11,
                  }}
                  formatter={(v) => (typeof v === "number" ? v.toFixed(3) : String(v))}
                  labelFormatter={(d) => format(new Date(d as string), "yyyy-MM-dd")}
                />
                <Line
                  type="monotone"
                  dataKey="score"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 font-mono text-[10px] text-neutral-600">
            CII = 0.40 × baseline + 0.60 × (0.25 unrest + 0.30 conflict +
            0.20 security + 0.25 information). Per-country baselines +
            multipliers published in CII-METHODOLOGY.md. Hourly Celery
            job, 24 h window. Coexists with composite via score_name.
          </p>
        </div>

        {/* Composite chart removed in #140 — CII v1 is the primary trend
         *  signal. Composite rows still land in the scores table for the
         *  ablation evidence the methodology doc promises. */}

        {/* CII per-country leaderboard (#142). Replaces the old "top 12
         *  by event count" panel — counting rows favoured high-volume
         *  English feeds (US / GB) and didn't reflect stress. Now ranks
         *  by latest cii_v1 score with a 30 d sparkline + 7 d delta. */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-5">
          <h3 className="mb-2 font-mono text-[11px] uppercase tracking-widest text-neutral-400">
            CII leaderboard · last 30 d
          </h3>
          <ul className="flex flex-col gap-1">
            {ciiCountries.length === 0 ? (
              <li className="px-2 py-1 font-mono text-[10px] text-neutral-600">
                No CII rows yet. Hourly worker populates the table.
              </li>
            ) : (
              ciiCountries.slice(0, 14).map((c) => {
                const arrow = c.delta7d > 0.01 ? "↑" : c.delta7d < -0.01 ? "↓" : "·"
                const arrowColor =
                  c.delta7d > 0.01
                    ? "text-rose-400"
                    : c.delta7d < -0.01
                      ? "text-emerald-400"
                      : "text-neutral-500"
                return (
                  <li
                    key={c.iso}
                    className="flex items-center gap-2 rounded px-2 py-1.5 text-[11px] hover:bg-neutral-900"
                    title={`unrest ${c.unrest.toFixed(0)} · conflict ${c.conflict.toFixed(0)} · security ${c.security.toFixed(0)} · information ${c.information.toFixed(0)}`}
                  >
                    <span className="w-6 text-center">{countryFlagEmoji(c.iso)}</span>
                    <span className="w-7 font-mono text-neutral-400">{c.iso}</span>
                    <span className="flex-1 truncate text-neutral-200">
                      {countryName(c.iso)}
                    </span>
                    <Sparkline values={c.history} color={ciiBandColor(c.current)} />
                    <span
                      className="w-12 text-right font-mono text-[10px] tabular-nums"
                      style={{ color: ciiBandColor(c.current) }}
                    >
                      {c.current.toFixed(3)}
                    </span>
                    <span
                      className={`w-10 text-right font-mono text-[10px] tabular-nums ${arrowColor}`}
                    >
                      {arrow}
                      {Math.abs(c.delta7d).toFixed(2)}
                    </span>
                  </li>
                )
              })
            )}
          </ul>
          <p className="mt-2 font-mono text-[10px] text-neutral-600">
            CII = published cii_v1 score per country. Sparkline = 30 d history.
            Delta = vs ~7 d ago. Hover row for the 4 sub-scores
            (unrest / conflict / security / information).
          </p>
        </div>

        {/* News feed — card layout with thumbnail + impact ranking.
         *  Pattern mirrors NIP (BasilSuhail/news-intelligence-platform)
         *  and the Portfolio-Design NewsSection.tsx. See issues #115 +
         *  #132. */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-12">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <h3 className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
                News feed
              </h3>
              <div className="inline-flex overflow-hidden rounded-md border border-neutral-800 font-mono text-[10px] uppercase tracking-wider">
                {(["impact", "time"] as const).map((opt) => (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => setNewsSort(opt)}
                    className={
                      "px-2 py-0.5 transition-colors " +
                      (newsSort === opt
                        ? "bg-amber-950/40 text-amber-200"
                        : "bg-neutral-900/50 text-neutral-500 hover:text-neutral-300")
                    }
                  >
                    {opt}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-1">
              {NEWS_FILTERS.map((f) => {
                const active = f.key === newsFilter
                const count = f.key === "all" ? allNews.length : allNews.filter(f.match).length
                return (
                  <button
                    key={f.key}
                    type="button"
                    onClick={() => setNewsFilter(f.key)}
                    className={
                      "rounded-md border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider transition-colors " +
                      (active
                        ? "border-cyan-700 bg-cyan-950/40 text-cyan-200"
                        : "border-neutral-800 bg-neutral-900/50 text-neutral-400 hover:border-neutral-700 hover:text-neutral-200")
                    }
                  >
                    {f.label}
                    <span className="ml-1 tabular-nums text-neutral-500">{count}</span>
                  </button>
                )
              })}
            </div>
          </div>
          {filteredNews.length === 0 ? (
            <p className="px-1 py-2 font-mono text-[10px] text-neutral-600">
              No news in this bucket yet. RSS feeds populate hourly.
            </p>
          ) : (
            <ul className="grid max-h-[34rem] grid-cols-1 gap-3 overflow-y-auto pr-1 md:grid-cols-2">
              {filteredNews.map((ev) => {
                const p = (ev.payload ?? {}) as Record<string, unknown>
                const url = typeof p?.source_url === "string" ? (p.source_url as string) : null
                const title = bestTitle(ev)
                const summary = bestSummary(ev)
                const sourceLabel = newsSourceLabel(ev)
                const city = typeof p?.city === "string" ? (p.city as string) : null
                const sev = typeof ev.severity === "number" ? ev.severity : 0
                const imageUrl =
                  typeof p?.image_url === "string" ? (p.image_url as string) : null
                const impact = impactScoreFor(ev)
                const firstLetter = title.charAt(0).toUpperCase() || "N"
                const sentiment =
                  typeof p?.sentiment === "number" ? (p.sentiment as number) : null
                const sentimentLabel =
                  typeof p?.sentiment_label === "string" ? (p.sentiment_label as string) : null
                const tileColor =
                  sentiment !== null ? sentimentBarColor(sentiment) : severityBarColor(sev)
                return (
                  <li key={ev.id}>
                    <a
                      href={url ?? "#"}
                      {...(url
                        ? { target: "_blank", rel: "noreferrer" }
                        : { onClick: (e) => e.preventDefault(), tabIndex: -1, "aria-disabled": true })}
                      className="group flex h-full gap-3 rounded-md border border-neutral-800 bg-neutral-900/40 p-3 transition-colors hover:border-neutral-700 hover:bg-neutral-900/80"
                    >
                      {imageUrl ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={imageUrl}
                          alt=""
                          loading="lazy"
                          referrerPolicy="no-referrer"
                          className="h-20 w-20 shrink-0 rounded object-cover ring-1 ring-neutral-800"
                          onError={(e) => {
                            (e.currentTarget as HTMLImageElement).style.display = "none"
                          }}
                        />
                      ) : (
                        <div
                          className="grid h-20 w-20 shrink-0 place-items-center rounded text-2xl font-semibold ring-1 ring-neutral-800"
                          style={{
                            backgroundColor: `${tileColor}22`,
                            color: tileColor,
                          }}
                          aria-hidden="true"
                          title={
                            sentiment !== null
                              ? `sentiment ${sentiment.toFixed(2)} (${sentimentLabel ?? ""})`
                              : `severity ${sev.toFixed(2)}`
                          }
                        >
                          {firstLetter}
                        </div>
                      )}
                      <div className="flex min-w-0 flex-1 flex-col">
                        <h4 className="text-[13px] font-medium leading-snug text-neutral-100 group-hover:text-white line-clamp-2">
                          {title}
                        </h4>
                        {summary && (
                          <p className="mt-1 text-[11.5px] leading-snug text-neutral-400 line-clamp-3">
                            {summary}
                          </p>
                        )}
                        <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-2 font-mono text-[10px] uppercase tracking-wider text-neutral-500">
                          <span className="rounded border border-neutral-800 bg-neutral-900 px-1.5 py-0.5 text-neutral-400">
                            {sourceLabel}
                          </span>
                          {ev.country && (
                            <span className="flex items-center gap-1">
                              <span>{countryFlagEmoji(ev.country)}</span>
                              <span>{ev.country}</span>
                            </span>
                          )}
                          {city && (
                            <span className="normal-case text-neutral-500">· {city}</span>
                          )}
                          {sentiment !== null && sentimentLabel && (
                            <span
                              className="rounded border px-1.5 py-0.5 tabular-nums"
                              style={{
                                color: sentimentBarColor(sentiment),
                                borderColor: `${sentimentBarColor(sentiment)}55`,
                                backgroundColor: `${sentimentBarColor(sentiment)}11`,
                              }}
                            >
                              {sentimentLabel} {sentiment.toFixed(2)}
                            </span>
                          )}
                          <span
                            className="rounded border border-amber-900/60 bg-amber-950/30 px-1.5 py-0.5 tabular-nums text-amber-300"
                            title="impact = 0.45 |sentiment| + 0.30 recency + 0.25 source weight"
                          >
                            impact {impact.toFixed(2)}
                          </span>
                          <span className="ml-auto tabular-nums text-neutral-600">
                            {relativeTime(ev.occurred_at)} · {format(new Date(ev.occurred_at), "HH:mm")}
                          </span>
                        </div>
                      </div>
                    </a>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        {/* Geographic convergence alerts — 1°×1° × 24 h × 3+ categories.
         *  Mirrors the WM convergence algorithm cited in issue #128. Pure
         *  reduce over the in-memory event buffer, no new fetcher. */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-12">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
              Convergence alerts · last {windowLabel}
            </h3>
            <span className="font-mono text-[10px] tabular-nums text-neutral-500">
              {convergenceAlerts.length} cells
            </span>
          </div>
          {convergenceAlerts.length === 0 ? (
            <p className="px-1 py-2 font-mono text-[10px] text-neutral-600">
              No 1°×1° cell currently has 3+ distinct categories firing in the last 24 h.
            </p>
          ) : (
            <ul className="flex flex-col gap-1">
              {convergenceAlerts.map((a) => (
                <li
                  key={a.key}
                  onClick={() => {
                    // Click → scroll the top viewport into view and dispatch
                    // a custom event the map pane listens for. See #145.
                    window.scrollTo({ top: 0, behavior: "smooth" })
                    window.dispatchEvent(
                      new CustomEvent("osint:flyto", {
                        detail: { lat: a.lat, lon: a.lon, zoom: 5 },
                      }),
                    )
                  }}
                  className="flex cursor-pointer flex-wrap items-center gap-2 rounded border border-neutral-800 bg-neutral-900/40 px-3 py-2 text-[11px] transition-colors hover:border-cyan-700 hover:bg-cyan-950/20"
                  title="Click to fly the map to this cell"
                >
                  <span
                    className={
                      "rounded-md border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider " +
                      (a.priority === "critical"
                        ? "border-rose-700 bg-rose-950/40 text-rose-200"
                        : "border-amber-700 bg-amber-950/40 text-amber-200")
                    }
                  >
                    {a.priority}
                  </span>
                  <span className="font-mono tabular-nums text-neutral-400">
                    {a.lat >= 0 ? `${a.lat}°N` : `${-a.lat}°S`} ·{" "}
                    {a.lon >= 0 ? `${a.lon}°E` : `${-a.lon}°W`}
                  </span>
                  <span className="flex flex-wrap items-center gap-1">
                    {a.categories.map((c) => (
                      <span
                        key={c}
                        className="rounded border border-neutral-800 bg-neutral-900 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-neutral-300"
                      >
                        {c}
                      </span>
                    ))}
                  </span>
                  <span className="ml-auto flex items-center gap-3 font-mono text-[10px] tabular-nums text-neutral-500">
                    <span>{a.eventCount} events</span>
                    <span className="text-neutral-300">score {a.score}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 font-mono text-[10px] text-neutral-600">
            Cell = 1° lat × 1° lon. Alert when 3+ distinct event categories
            co-occur in the same cell within the last 24 h. Score = 25 ×
            categories + min(25, events × 2). Critical = 4+ categories or
            score ≥ 90.
          </p>
        </div>

        {/* Severity histogram — last 24 h */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-12">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
              Severity histogram · last {windowLabel}
            </h3>
            <span className="font-mono text-[10px] tabular-nums text-neutral-500">
              {severityBuckets.reduce((a, b) => a + b.n, 0).toLocaleString()} events
            </span>
          </div>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={severityBuckets} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="rgba(115,115,115,0.15)" strokeDasharray="4 4" />
                <XAxis
                  dataKey="bucket"
                  stroke="rgba(115,115,115,0.6)"
                  fontSize={10}
                  tickFormatter={(v) => v}
                />
                <YAxis
                  stroke="rgba(115,115,115,0.6)"
                  fontSize={10}
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={{
                    background: "rgba(10,10,10,0.92)",
                    border: "1px solid rgba(82,82,82,0.6)",
                    fontFamily: "monospace",
                    fontSize: 11,
                  }}
                  formatter={(v) => (typeof v === "number" ? v.toLocaleString() : String(v))}
                  labelFormatter={(_, payload) => {
                    const p = payload?.[0]?.payload as { range?: string } | undefined
                    return p?.range ? `severity ${p.range}` : "severity"
                  }}
                />
                <Bar dataKey="n" radius={[2, 2, 0, 0]}>
                  {severityBuckets.map((s) => (
                    <Cell key={s.bucket} fill={s.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 font-mono text-[10px] text-neutral-600">
            Distribution of event severities for rows whose occurred_at is in
            the last 24 h. A long right tail (orange / red bars) flags a
            high-severity cluster worth zooming the map in on.
          </p>
        </div>

        {/* Cyber-threat rollup (#177). Surfaces abuse.ch URLhaus + Feodo
         *  rows shipped via #163. */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-6">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
              Cyber threats · last {windowLabel}
            </h3>
            <span className="font-mono text-[10px] tabular-nums text-neutral-500">
              {cyberThreats.total} indicators
            </span>
          </div>
          {cyberThreats.tagBreakdown.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1">
              {cyberThreats.tagBreakdown.map((t) => (
                <span
                  key={t.tag}
                  className="rounded border border-rose-900/60 bg-rose-950/30 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-rose-300"
                >
                  {t.tag} · {t.n}
                </span>
              ))}
            </div>
          )}
          {cyberThreats.rows.length === 0 ? (
            <p className="px-1 py-2 font-mono text-[10px] text-neutral-600">
              No abuse.ch rows in this window yet.
            </p>
          ) : (
            <ul className="flex max-h-72 flex-col gap-1 overflow-y-auto pr-1">
              {cyberThreats.rows.map(({ ev, primary, status, severity }) => {
                const p = (ev.payload ?? {}) as Record<string, unknown>
                const target = (p.url as string | null) ?? (p.dst_ip as string | null) ?? "—"
                return (
                  <li
                    key={ev.id}
                    className="flex items-center gap-2 rounded px-2 py-1 text-[11px] hover:bg-neutral-900"
                  >
                    <span
                      className="inline-block h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: severityBarColor(severity) }}
                      aria-hidden="true"
                    />
                    <span className="w-12 font-mono text-[10px] uppercase text-neutral-500">
                      {ev.source === "abuse-ch-feodo" ? "feodo" : "urlhaus"}
                    </span>
                    <span className="rounded border border-neutral-800 bg-neutral-900 px-1 font-mono text-[10px] uppercase tracking-wider text-neutral-300">
                      {primary}
                    </span>
                    {status && (
                      <span className="font-mono text-[10px] uppercase text-neutral-500">
                        {status}
                      </span>
                    )}
                    <span className="flex-1 truncate font-mono text-[10px] text-neutral-400">
                      {target}
                    </span>
                    <span className="font-mono text-[10px] tabular-nums text-neutral-600">
                      {relativeTime(ev.occurred_at)}
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        {/* Polymarket top-stress markets (#177 companion). */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-6">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
              Polymarket · top stress markets
            </h3>
            <span className="font-mono text-[10px] tabular-nums text-neutral-500">
              {polyTopStress.length} of {events.filter((e) => e.source === "polymarket").length}
            </span>
          </div>
          {polyTopStress.length === 0 ? (
            <p className="px-1 py-2 font-mono text-[10px] text-neutral-600">
              No Polymarket rows yet. 30 min cadence.
            </p>
          ) : (
            <ul className="flex max-h-72 flex-col gap-1 overflow-y-auto pr-1">
              {polyTopStress.map(({ ev, price, question }) => (
                <li
                  key={ev.id}
                  className="flex items-center gap-2 rounded px-2 py-1 text-[11px] hover:bg-neutral-900"
                >
                  <span
                    className="inline-block h-2 w-2 shrink-0 rounded-full"
                    style={{
                      backgroundColor: severityBarColor(ev.severity ?? 0),
                    }}
                    aria-hidden="true"
                  />
                  <span className="flex-1 truncate text-neutral-300">{question}</span>
                  <span className="font-mono text-[10px] tabular-nums text-neutral-500">
                    p = {price !== null ? price.toFixed(2) : "?"}
                  </span>
                  <span
                    className="font-mono text-[10px] tabular-nums"
                    style={{ color: severityBarColor(ev.severity ?? 0) }}
                  >
                    s {ev.severity?.toFixed(2)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 font-mono text-[10px] text-neutral-600">
            Severity = 1 − |p − 0.5| × 2 — peaks at maximum uncertainty.
          </p>
        </div>

        {/* Source latency (#144). Replaces the old buffer-bar source-health
         *  panel with a real read against the ingest_health table. Each
         *  row shows last_success age vs the source's expected cadence
         *  from the beat schedule. Green / amber / red bands match the
         *  watchdog thresholds (1.5x = warn, 3x = stale). */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-5">
          <h3 className="mb-2 font-mono text-[11px] uppercase tracking-widest text-neutral-400">
            Source latency · last_success vs cadence
          </h3>
          {sourceLatency.length === 0 ? (
            <p className="px-1 py-2 font-mono text-[10px] text-neutral-600">
              No ingest_health rows yet. Workers populate the table on every
              fetcher tick.
            </p>
          ) : (
            <ul className="flex max-h-72 flex-col gap-1 overflow-y-auto pr-1">
              {sourceLatency.map((r) => {
                const dotColor =
                  r.band === "stale"
                    ? "#ef4444"
                    : r.band === "warn"
                      ? "#f59e0b"
                      : "#22c55e"
                return (
                  <li
                    key={r.source}
                    className="flex items-center gap-2 rounded px-2 py-1.5 text-[11px] hover:bg-neutral-900"
                    title={`cadence ${r.cadenceMin ?? "?"} min · failures 24h: ${r.failure24h}`}
                  >
                    <span
                      className="inline-block h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: dotColor }}
                      aria-hidden="true"
                    />
                    <span className="w-32 truncate font-mono text-neutral-300">{r.source}</span>
                    <span className="flex-1 font-mono text-[10px] text-neutral-500">
                      cadence {r.cadenceMin == null ? "?" : `${r.cadenceMin} m`}
                    </span>
                    <span
                      className="w-16 text-right font-mono text-[10px] tabular-nums"
                      style={{ color: dotColor }}
                    >
                      {ageLabel(r.ageMin)}
                    </span>
                    {r.failure24h > 0 && (
                      <span className="ml-1 rounded border border-rose-900 bg-rose-950/40 px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-rose-300">
                        {r.failure24h} fail
                      </span>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
          <p className="mt-2 font-mono text-[10px] text-neutral-600">
            Green = within cadence. Amber = 1.5x cadence overdue. Red = 3x
            overdue. Cadences match the beat schedule in app/tasks.py.
          </p>
        </div>
      </div>

      <p className="mt-6 font-mono text-[10px] uppercase tracking-widest text-neutral-700">
        Scroll up for live map + globe
      </p>
    </section>
  )
}

/** Top-level export — separate so the imports stay tidy in SplitLayout. */
export default DashboardSection
