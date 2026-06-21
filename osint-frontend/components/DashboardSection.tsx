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

  /** News feed: latest 40 RSS / police news rows. Map-side category=news.
   *  Also matches any source slug that starts with rss- or equals uk-police so
   *  we don't depend on the SourceKey enum (still landing in #107). */
  const newsFeed = useMemo(() => {
    return events
      .filter((ev) => {
        const s = (ev.source ?? "").toLowerCase()
        return ev.category === "news" || s.startsWith("rss-") || s === "uk-police"
      })
      .slice(0, 40)
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

        {/* News feed */}
        <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4 lg:col-span-7">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-mono text-[11px] uppercase tracking-widest text-neutral-400">
              News feed
            </h3>
            <span className="font-mono text-[10px] tabular-nums text-neutral-500">
              {newsFeed.length}
            </span>
          </div>
          <ul className="flex max-h-72 flex-col gap-1 overflow-y-auto">
            {newsFeed.length === 0 ? (
              <li className="px-2 py-1 font-mono text-[10px] text-neutral-600">
                No news yet. RSS feeds populate hourly.
              </li>
            ) : (
              newsFeed.map((ev) => {
                const p = (ev.payload ?? {}) as Record<string, unknown>
                const url =
                  typeof p?.source_url === "string" ? (p.source_url as string) : null
                const Wrapper = url ? "a" : "div"
                return (
                  <li key={ev.id}>
                    <Wrapper
                      {...(url
                        ? { href: url, target: "_blank", rel: "noreferrer" }
                        : {})}
                      className="flex items-center gap-2 rounded px-2 py-1.5 text-[11px] hover:bg-neutral-900"
                    >
                      <span
                        className="inline-block h-3 w-1 shrink-0 rounded-sm"
                        style={{
                          backgroundColor: severityBarColor(
                            typeof ev.severity === "number" ? ev.severity : 0,
                          ),
                        }}
                      />
                      <span className="w-6 text-center">
                        {ev.country ? countryFlagEmoji(ev.country) : ""}
                      </span>
                      <span className="flex-1 truncate text-neutral-200">
                        {bestTitle(ev)}
                      </span>
                      <span className="shrink-0 font-mono text-[10px] tabular-nums text-neutral-500">
                        {format(new Date(ev.occurred_at), "HH:mm")}
                      </span>
                    </Wrapper>
                  </li>
                )
              })
            )}
          </ul>
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
