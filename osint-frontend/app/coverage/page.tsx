"use client"

import { useMemo, useState } from "react"
import useSWR from "swr"
import { SystemStatusBar } from "@/components/SystemStatusBar"
import { fetchCoverageReport, type CoverageStat } from "@/lib/analytics"

const REFRESH_MS = 10 * 60_000

type SortKey = keyof Pick<
  CoverageStat,
  "total_events" | "events_per_month" | "global_share" | "fatalities_per_event" | "coverage_months"
>

const COLUMNS: { key: SortKey; label: string; render: (s: CoverageStat) => string }[] = [
  { key: "coverage_months", label: "months", render: (s) => String(s.coverage_months) },
  { key: "total_events", label: "events", render: (s) => s.total_events.toLocaleString() },
  { key: "events_per_month", label: "events/mo", render: (s) => s.events_per_month.toFixed(1) },
  { key: "global_share", label: "share", render: (s) => `${(s.global_share * 100).toFixed(2)}%` },
  {
    key: "fatalities_per_event",
    label: "fatal/event",
    render: (s) => s.fatalities_per_event.toFixed(2),
  },
]

const HEAD = "px-2 py-1 font-mono text-[9px] uppercase tracking-wide text-neutral-500"
const CELL = "px-2 py-1 text-right font-mono text-[11px] tabular-nums text-neutral-300"

export default function CoveragePage() {
  const { data, error } = useSWR("coverage-report", fetchCoverageReport, {
    refreshInterval: REFRESH_MS,
    revalidateOnFocus: false,
  })
  const [sortKey, setSortKey] = useState<SortKey>("total_events")
  const [limit, setLimit] = useState<number>(30)

  const rows = useMemo(() => {
    const stats = [...(data?.stats ?? [])]
    stats.sort((a, b) => b[sortKey] - a[sortKey])
    return stats.slice(0, limit)
  }, [data, sortKey, limit])

  return (
    <div className="flex min-h-screen flex-col bg-neutral-950">
      <SystemStatusBar />
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-3 p-4">
        <header>
          <h1 className="text-lg font-semibold text-neutral-100">Coverage bias</h1>
          <p className="font-mono text-[10px] uppercase tracking-wide text-neutral-500">
            how unevenly countries are covered — measured, not assumed
          </p>
        </header>

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
                <div
                  key={n}
                  className="rounded-xl border border-neutral-800 bg-neutral-900/50 px-4 py-2"
                >
                  <p className="font-mono text-lg tabular-nums text-cyan-300">
                    {(share * 100).toFixed(1)}%
                  </p>
                  <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-500">
                    of volume in top {n}
                  </p>
                </div>
              ))}
              <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 px-4 py-2">
                <p className="font-mono text-lg tabular-nums text-neutral-200">
                  {data.countries}
                </p>
                <p className="font-mono text-[9px] uppercase tracking-wide text-neutral-500">
                  countries · {data.global_events.toLocaleString()} events
                </p>
              </div>
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
                            {col.label}
                            {sortKey === col.key ? " ↓" : ""}
                          </button>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((stat) => (
                      <tr key={stat.country} className="border-b border-neutral-800/50">
                        <td className="px-2 py-1 font-mono text-[11px] text-neutral-200">
                          {stat.country}
                        </td>
                        {COLUMNS.map((col) => (
                          <td key={col.key} className={CELL}>
                            {col.render(stat)}
                          </td>
                        ))}
                      </tr>
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
              events/mo doubles as each country&apos;s own baseline mean · generated{" "}
              {new Date(data.generated_at).toLocaleString()} · regenerate with `make coverage`
            </p>
          </>
        )}
      </main>
    </div>
  )
}
