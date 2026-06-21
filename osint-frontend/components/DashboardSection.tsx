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
import { colorForEvent, type EventRow, type ScoreRow } from "@/lib/types"

const COMPOSITE_BUCKETS = 30

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

/** Last 30 d composite-score time series, averaged across all countries. */
function useCompositeSeries(): { day: string; score: number; n: number }[] {
  const [data, setData] = useState<ScoreRow[]>([])
  useEffect(() => {
    const supabase = getSupabase()
    if (!supabase) return
    const since = subDays(new Date(), COMPOSITE_BUCKETS).toISOString()
    supabase
      .from("scores")
      .select("*")
      .gte("bucket_start", since)
      .order("bucket_start", { ascending: true })
      .limit(5000)
      .then(({ data: rows, error }) => {
        if (!error && rows) setData(rows as ScoreRow[])
      })
  }, [])

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

interface DashboardSectionProps {
  configured: boolean
}

export function DashboardSection({ configured }: DashboardSectionProps) {
  const events = useEvents()
  const series = useCompositeSeries()

  /** Top 12 countries by event count in the current buffer. */
  const topCountries = useMemo(() => {
    const counts = new Map<string, number>()
    for (const ev of events) {
      if (!ev.country) continue
      counts.set(ev.country, (counts.get(ev.country) ?? 0) + 1)
    }
    return Array.from(counts.entries())
      .map(([iso, n]) => ({ iso, n }))
      .sort((a, b) => b.n - a.n)
      .slice(0, 12)
  }, [events])

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

  const filteredNews = useMemo(() => {
    const f = NEWS_FILTERS.find((x) => x.key === newsFilter) ?? NEWS_FILTERS[0]
    return allNews.filter(f.match).slice(0, 30)
  }, [allNews, newsFilter])

  /** Severity histogram: events in last 24 h binned by severity into 10
   *  fixed-width buckets [0, 0.1) … [0.9, 1.0]. Drives the bar chart.
   *  Helps spot a hot tail (high-severity cluster) without scanning the
   *  whole map. Severity is the JRC-normalised stress score per event. */
  const severityBuckets = useMemo(() => {
    const BUCKETS = 10
    const counts = new Array<number>(BUCKETS).fill(0)
    const cutoff = Date.now() - 24 * 60 * 60 * 1000
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
  }, [events])

  /** Source health: row count per source in current buffer. Drives the bars. */
  const sourceCounts = useMemo(() => {
    const map = new Map<string, number>()
    for (const ev of events) {
      map.set(ev.source, (map.get(ev.source) ?? 0) + 1)
    }
    return Array.from(map.entries())
      .map(([source, n]) => ({ source, n }))
      .sort((a, b) => b.n - a.n)
      .slice(0, 12)
  }, [events])

  if (!configured) return null

  return (
    <section
      aria-label="Dashboard charts"
      className="relative w-full bg-neutral-950 px-4 py-8 text-neutral-100 sm:px-6 lg:px-10"
    >
      <div className="mb-6 flex items-center justify-between">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
          Dashboard
        </h2>
        <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-600">
          {events.length.toLocaleString()} events in buffer
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-12">
        {/* Composite time series */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-7">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
              Composite score (mean, last {COMPOSITE_BUCKETS} d)
            </h3>
            <span className="font-mono text-[10px] tabular-nums text-neutral-500">
              {series.length} days
            </span>
          </div>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
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
                  stroke="#22d3ee"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 font-mono text-[10px] text-neutral-600">
            Composite is the average JRC-normalised stress per day across every
            country with a score. Flat 0.5 means the rolling-z window has no
            spread yet; widens as historical depth grows.
          </p>
        </div>

        {/* Top countries */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-5">
          <h3 className="mb-2 font-mono text-[11px] uppercase tracking-widest text-neutral-400">
            Top 12 countries · events in buffer
          </h3>
          <ul className="flex flex-col gap-1">
            {topCountries.length === 0 ? (
              <li className="px-2 py-1 font-mono text-[10px] text-neutral-600">No country data.</li>
            ) : (
              topCountries.map(({ iso, n }) => (
                <li
                  key={iso}
                  className="flex items-center gap-2 rounded px-2 py-1.5 text-[11px] hover:bg-neutral-900"
                >
                  <span className="w-6 text-center">{countryFlagEmoji(iso)}</span>
                  <span className="w-7 font-mono text-neutral-400">{iso}</span>
                  <span className="flex-1 truncate text-neutral-200">{countryName(iso)}</span>
                  <span className="w-12 text-right font-mono text-[10px] tabular-nums text-neutral-300">
                    {n.toLocaleString()}
                  </span>
                </li>
              ))
            )}
          </ul>
        </div>

        {/* News feed — card layout with headline + summary + source link.
         *  Pattern mirrors the news cards in BasilSuhail/Portfolio-Design
         *  (NewsSection.tsx). See issue #115. */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-7">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
              News feed
            </h3>
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
            <ul className="flex max-h-[26rem] flex-col gap-2 overflow-y-auto pr-1">
              {filteredNews.map((ev) => {
                const p = (ev.payload ?? {}) as Record<string, unknown>
                const url = typeof p?.source_url === "string" ? (p.source_url as string) : null
                const title = bestTitle(ev)
                const summary = bestSummary(ev)
                const sourceLabel = newsSourceLabel(ev)
                const city = typeof p?.city === "string" ? (p.city as string) : null
                const sev = typeof ev.severity === "number" ? ev.severity : 0
                return (
                  <li key={ev.id}>
                    <a
                      href={url ?? "#"}
                      {...(url
                        ? { target: "_blank", rel: "noreferrer" }
                        : { onClick: (e) => e.preventDefault(), tabIndex: -1, "aria-disabled": true })}
                      className="group flex gap-3 rounded-md border border-neutral-800 bg-neutral-900/40 p-3 transition-colors hover:border-neutral-700 hover:bg-neutral-900/80"
                    >
                      <span
                        className="mt-1 inline-block h-10 w-1 shrink-0 rounded-sm"
                        style={{ backgroundColor: severityBarColor(sev) }}
                        aria-hidden="true"
                      />
                      <div className="min-w-0 flex-1">
                        <h4 className="text-[12.5px] font-medium leading-snug text-neutral-100 group-hover:text-white line-clamp-2">
                          {title}
                        </h4>
                        {summary && (
                          <p className="mt-1 text-[11px] leading-snug text-neutral-400 line-clamp-2">
                            {summary}
                          </p>
                        )}
                        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10px] uppercase tracking-wider text-neutral-500">
                          <span className="rounded border border-neutral-800 bg-neutral-900 px-1.5 py-0.5 text-neutral-400">
                            {sourceLabel}
                          </span>
                          {ev.country && (
                            <span className="flex items-center gap-1">
                              <span>{countryFlagEmoji(ev.country)}</span>
                              <span>{ev.country}</span>
                            </span>
                          )}
                          {city && <span className="normal-case text-neutral-500">· {city}</span>}
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

        {/* Severity histogram — last 24 h */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-12">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
              Severity histogram · last 24 h
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

        {/* Source health */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-5">
          <h3 className="mb-2 font-mono text-[11px] uppercase tracking-widest text-neutral-400">
            Source health · events in buffer
          </h3>
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={sourceCounts}
                layout="vertical"
                margin={{ top: 4, right: 16, left: 50, bottom: 0 }}
              >
                <CartesianGrid stroke="rgba(115,115,115,0.15)" strokeDasharray="4 4" />
                <XAxis
                  type="number"
                  stroke="rgba(115,115,115,0.6)"
                  fontSize={10}
                />
                <YAxis
                  type="category"
                  dataKey="source"
                  stroke="rgba(115,115,115,0.6)"
                  fontSize={10}
                  width={90}
                />
                <Tooltip
                  contentStyle={{
                    background: "rgba(10,10,10,0.92)",
                    border: "1px solid rgba(82,82,82,0.6)",
                    fontFamily: "monospace",
                    fontSize: 11,
                  }}
                  formatter={(v) => (typeof v === "number" ? v.toLocaleString() : String(v))}
                />
                <Bar dataKey="n" radius={[2, 2, 2, 2]}>
                  {sourceCounts.map((s) => (
                    <Cell
                      key={s.source}
                      fill={colorForEvent({
                        source: s.source,
                        category: "",
                      } as unknown as EventRow)}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
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
