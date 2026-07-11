"use client"

import React, { useMemo, useState } from "react"
import useSWR from "swr"
import { fetchCountryScores, fetchCoverageReport, type CoverageStat } from "@/lib/analytics"
import { countryName } from "@/lib/countryName"
import { BarRow, Hint, Sparkline, StatTile } from "./viz"

const REFRESH_MS = 10 * 60_000

type SortKey = keyof Pick<
  CoverageStat,
  "total_events" | "events_per_month" | "global_share" | "fatalities_per_event" | "coverage_months"
>

/** Fatalities/event severity: colour + symbol, never colour alone. */
function fatalTone(v: number): { cls: string; mark: string; word: string } {
  if (v >= 1) return { cls: "text-red-400", mark: "▲", word: "severe blind spot" }
  if (v >= 0.1) return { cls: "text-amber-300", mark: "△", word: "under-covered" }
  return { cls: "text-neutral-300", mark: "", word: "well covered" }
}

function CountryDrilldown({ stat }: { stat: CoverageStat }) {
  const { data, error } = useSWR(["country-scores", stat.country], () =>
    fetchCountryScores(stat.country),
  )
  const t = fatalTone(stat.fatalities_per_event)
  return (
    <div className="border-l-2 border-neutral-800 bg-neutral-950/40 px-4 py-2">
      <p className="mb-1 font-mono text-[9px] uppercase tracking-wide text-neutral-500">
        <Hint term={`${countryName(stat.country)} — composite stress index over time`}>
          The country&apos;s monthly composite stress score (0 calm → 1 stressed), judged
          against its own history. Hover the line for exact months. This is the number the
          forecasting exam grades — read it as &quot;how unusual was this month for this
          country&quot;, never as a cross-country comparison.
        </Hint>
      </p>
      {error ? (
        <p className="font-mono text-[10px] text-red-400">score history unavailable</p>
      ) : !data ? (
        <p className="font-mono text-[10px] text-neutral-500">loading…</p>
      ) : (
        <Sparkline
          points={data.map((d) => ({
            label: d.bucket_start.slice(0, 7),
            value: d.score_value,
          }))}
        />
      )}
      <p className="mt-1 text-[11px] leading-relaxed text-neutral-400">
        {countryName(stat.country)} has {stat.coverage_months} months of history,{" "}
        {stat.events_per_month.toFixed(1)} recorded events per month (its own baseline),{" "}
        {(stat.global_share * 100).toFixed(2)}% of global attention, and{" "}
        {stat.fatalities_per_event.toFixed(2)} fatalities per recorded event — {t.word}.
      </p>
    </div>
  )
}

const COLUMNS: {
  key: SortKey
  label: string
  hint: string
  render: (s: CoverageStat) => React.ReactNode
}[] = [
  {
    key: "coverage_months",
    label: "months of history",
    hint: "How long we have been recording this country. Short history means its baselines are shaky — treat its other numbers with extra caution.",
    render: (s) => String(s.coverage_months),
  },
  {
    key: "total_events",
    label: "recorded events",
    hint: "Everything the pipeline has ever recorded about this country. Raw attention, not importance.",
    render: (s) => s.total_events.toLocaleString(),
  },
  {
    key: "events_per_month",
    label: "events per month",
    hint: "Average recorded events per month — this doubles as the country's own baseline: spikes are judged against this number, not against other countries.",
    render: (s) => s.events_per_month.toFixed(1),
  },
  {
    key: "global_share",
    label: "share of global attention",
    hint: "This country's slice of ALL recorded events — the loudness ranking. High share = the world talks about it constantly; its spikes are often just volume.",
    render: (s) => `${(s.global_share * 100).toFixed(2)}%`,
  },
  {
    key: "fatalities_per_event",
    label: "fatalities per event",
    hint: "Deaths per recorded event. Near zero (US ~0.01): everything gets reported, however minor. High (Afghanistan ~3): only catastrophe makes the record. High values mark the dashboard's blind spots — ▲ severe, △ notable.",
    render: (s) => {
      const t = fatalTone(s.fatalities_per_event)
      return (
        <span className={t.cls}>
          {s.fatalities_per_event.toFixed(2)} {t.mark}
        </span>
      )
    },
  },
]

const HEAD = "px-2 py-1 font-mono text-[9px] uppercase tracking-wide text-neutral-500"
const CELL = "px-2 py-1 text-right font-mono text-[11px] tabular-nums text-neutral-300"

/** Coverage-bias table — how unevenly countries are covered. Deck card / fullscreen body. */
export function CoveragePanel() {
  const { data, error } = useSWR("coverage-report", fetchCoverageReport, {
    refreshInterval: REFRESH_MS,
    revalidateOnFocus: false,
  })
  const [sortKey, setSortKey] = useState<SortKey>("total_events")
  const [expanded, setExpanded] = useState<string | null>(null)
  const [limit, setLimit] = useState<number>(30)

  const rows = useMemo(() => {
    const stats = [...(data?.stats ?? [])]
    stats.sort((a, b) => b[sortKey] - a[sortKey])
    return stats.slice(0, limit)
  }, [data, sortKey, limit])

  const topTen = useMemo(() => {
    const stats = [...(data?.stats ?? [])]
    stats.sort((a, b) => b.global_share - a.global_share)
    return stats.slice(0, 10)
  }, [data])
  const maxShare = Math.max(0.001, ...topTen.map((s) => s.global_share))

  return (
    <div className="flex flex-col gap-3">
      <p className="font-mono text-[10px] uppercase tracking-wide text-neutral-500">
        the dashboard&apos;s own blind spots — who gets talked about, who only makes the record
        when people die
      </p>

      {error ? (
        <section className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
          <p className="font-mono text-[11px] text-red-400">
            no coverage report — run `make coverage`
          </p>
        </section>
      ) : !data ? (
        <section className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
          <p className="font-mono text-[11px] text-neutral-500">loading…</p>
        </section>
      ) : (
        <>
          <section className="flex flex-wrap gap-2">
            {Object.entries(data.top_share).map(([n, share]) => (
              <StatTile
                key={n}
                value={`${(share * 100).toFixed(1)}%`}
                label={`of all attention goes to just ${n} countries`}
                tone="text-cyan-300"
                hint={`The ${n} loudest countries absorb ${(share * 100).toFixed(1)}% of every event this system records. Media attention is that concentrated — which is why countries are judged against their own history, never against each other's volume.`}
              />
            ))}
            <StatTile
              value={data.countries}
              label={`countries · ${data.global_events.toLocaleString()} recorded events`}
              hint="How many countries appear in the record at all, and the total number of events ever recorded across them."
            />
          </section>

          <section className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-3">
            <p className="mb-1 font-mono text-[9px] uppercase tracking-wide text-neutral-500">
              <Hint term="the loudness top 10 — share of global attention">
                The ten countries the record talks about most. Longer bar = louder. A spike in a
                loud country is often just volume; a small spike in a quiet country can matter
                far more.
              </Hint>
            </p>
            {topTen.map((s) => (
              <BarRow
                key={s.country}
                label={countryName(s.country)}
                value={`${(s.global_share * 100).toFixed(1)}%`}
                fraction={s.global_share / maxShare}
                hint={`${countryName(s.country)}: ${(s.global_share * 100).toFixed(2)}% of all recorded events · ${s.events_per_month.toFixed(1)} events/month · ${s.fatalities_per_event.toFixed(2)} fatalities per event (${fatalTone(s.fatalities_per_event).word}).`}
              />
            ))}
          </section>

          <section className="overflow-hidden rounded-xl border border-neutral-800 bg-neutral-900/50">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-neutral-800 text-left">
                    <th className={HEAD}>country</th>
                    {COLUMNS.map((col) => (
                      <th key={col.key} className={`${HEAD} text-right`}>
                        <button
                          onClick={() => setSortKey(col.key)}
                          className={
                            sortKey === col.key ? "text-cyan-300" : "hover:text-neutral-200"
                          }
                        >
                          <Hint term={col.label}>
                            {col.hint} Click to sort by this column.
                          </Hint>
                          <span className={sortKey === col.key ? "" : "opacity-0"}> ↓</span>
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((stat) => (
                    <React.Fragment key={stat.country}>
                      <tr
                        className="cursor-pointer border-b border-neutral-800/50 hover:bg-neutral-900/60"
                        onClick={() =>
                          setExpanded((v) => (v === stat.country ? null : stat.country))
                        }
                      >
                        <td className="max-w-44 truncate px-2 py-1 text-[11px] text-neutral-200">
                          {expanded === stat.country ? "▾ " : "▸ "}
                          {countryName(stat.country)}{" "}
                          <span className="font-mono text-[9px] text-neutral-500">
                            {stat.country}
                          </span>
                        </td>
                        {COLUMNS.map((col) => (
                          <td key={col.key} className={CELL}>
                            {col.render(stat)}
                          </td>
                        ))}
                      </tr>
                      {expanded === stat.country ? (
                        <tr className="border-b border-neutral-800/50">
                          <td colSpan={COLUMNS.length + 1} className="p-0">
                            <CountryDrilldown stat={stat} />
                          </td>
                        </tr>
                      ) : null}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
            </div>
            {data.stats.length > limit ? (
              <button
                onClick={() => setLimit((v) => v + 50)}
                className="w-full border-t border-neutral-800 py-1.5 font-mono text-[10px] uppercase tracking-wide text-neutral-500 hover:text-neutral-200"
              >
                show more ({data.stats.length - limit} hidden)
              </button>
            ) : null}
          </section>

          <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-600">
            click a country for its stress-index history · ▲ = high fatalities per event: this country only makes the record when people die —
            read its small spikes seriously · generated{" "}
            {new Date(data.generated_at).toLocaleString()} · regenerate with `make coverage`
          </p>
        </>
      )}
    </div>
  )
}
