"use client"

import { useMemo } from "react"
import { useEvents } from "@/app/providers"
import { useLatestScores } from "@/lib/queries"
import { scoreTextColor } from "@/lib/types"
import { worldStats } from "@/lib/worldStats"
import { useRightPaneModeStore } from "@/stores/rightPaneModeStore"

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

function StatCell({
  value,
  label,
  accent,
}: {
  value: string
  label: string
  accent?: boolean
}) {
  return (
    <div className="flex flex-1 flex-col gap-0.5">
      <span
        className={
          "font-mono text-2xl font-semibold leading-none tabular-nums " +
          (accent ? "text-cyan-400" : "text-neutral-100")
        }
      >
        {value}
      </span>
      <span className="font-mono text-[9px] uppercase tracking-widest text-neutral-500">
        {label}
      </span>
    </div>
  )
}

/** Compact events-over-time sparkline (ACLED right-column chart). */
function Sparkline({ points }: { points: number[] }) {
  const max = Math.max(1, ...points)
  const w = 100
  const h = 28
  const n = points.length
  const path = points
    .map((v, i) => {
      const x = n <= 1 ? 0 : (i / (n - 1)) * w
      const y = h - (v / max) * h
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(" ")
  const area = `${path} L${w},${h} L0,${h} Z`
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      className="h-8 w-full"
      aria-hidden
    >
      <path d={area} fill="rgb(34 211 238 / 0.12)" />
      <path d={path} fill="none" stroke="rgb(34 211 238 / 0.9)" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

/** Default "world" mode of the right pane: totals + events sparkline +
 *  countries ranked by frequency (ACLED-style). Rows are clickable and lock
 *  the pane to that country's detail (#252). */
export function WorldStatusPanel() {
  const events = useEvents()
  const { byCountry } = useLatestScores()
  const openCountry = useRightPaneModeStore((s) => s.openCountry)

  const stats = useMemo(() => worldStats(events), [events])
  const maxCount = stats.topCountries[0]?.count ?? 1

  return (
    <div className="flex h-full w-full flex-col gap-3 overflow-y-auto bg-neutral-950 p-3">
      {/* Totals card */}
      <section className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-3">
        <h2 className="mb-2 font-mono text-[10px] uppercase tracking-widest text-neutral-400">
          All events · live
        </h2>
        <div className="flex items-end gap-3">
          <StatCell value={stats.total.toLocaleString()} label="Events" accent />
          <StatCell value={stats.activeCountries.toLocaleString()} label="Countries" />
          <StatCell value={stats.activeSources.toLocaleString()} label="Sources" />
        </div>
        <div className="mt-3">
          <span className="font-mono text-[9px] uppercase tracking-widest text-neutral-500">
            ↑ Events over time
          </span>
          <Sparkline points={stats.spark} />
        </div>
      </section>

      {/* Ranked countries */}
      <section className="flex min-h-0 flex-1 flex-col rounded-lg border border-neutral-800 bg-neutral-900/40 p-3">
        <h2 className="mb-2 font-mono text-[10px] uppercase tracking-widest text-neutral-400">
          Highest frequency of events
        </h2>
        {stats.topCountries.length === 0 ? (
          <p className="py-6 text-center text-xs text-neutral-600">No events in view.</p>
        ) : (
          <ul className="-mx-1 flex-1 space-y-0.5 overflow-y-auto">
            {stats.topCountries.map(({ country, count }) => {
              const score = byCountry.get(country)
              return (
                <li key={country}>
                  <button
                    type="button"
                    onClick={() => openCountry(country)}
                    className="group flex w-full items-center gap-2 rounded-md px-1 py-1 text-left hover:bg-neutral-800/60"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`https://flagcdn.com/20x15/${country.toLowerCase()}.png`}
                      alt=""
                      width={20}
                      height={15}
                      className="shrink-0 rounded-[2px] border border-neutral-800"
                    />
                    <span className="w-28 shrink-0 truncate text-xs text-neutral-200">
                      {countryName(country)}
                    </span>
                    <span className="relative h-2.5 flex-1 overflow-hidden rounded-full bg-neutral-800/70">
                      <span
                        className="absolute inset-y-0 left-0 rounded-full"
                        style={{
                          width: `${Math.max(4, (count / maxCount) * 100)}%`,
                          backgroundColor: score ? scoreTextColor(score.score) : "rgb(56 189 248 / 0.85)",
                        }}
                      />
                    </span>
                    <span className="w-12 shrink-0 text-right font-mono text-[11px] tabular-nums text-neutral-400">
                      {count.toLocaleString()}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>
    </div>
  )
}
