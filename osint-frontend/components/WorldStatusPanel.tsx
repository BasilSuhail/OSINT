"use client"

import { useMemo } from "react"
import { useEvents } from "@/app/providers"
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

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 10_000) return `${(n / 1000).toFixed(0)}k`
  return n.toLocaleString()
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
    <div className="flex flex-1 flex-col gap-1">
      <span
        className={
          "font-mono text-[28px] font-semibold leading-none tabular-nums " +
          (accent ? "text-sky-400" : "text-neutral-200")
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

/** Events-over-time sparkline with area fill + baseline (ACLED right column). */
function Sparkline({ points }: { points: number[] }) {
  const max = Math.max(1, ...points)
  const w = 100
  const h = 40
  const n = points.length
  const line = points
    .map((v, i) => {
      const x = n <= 1 ? 0 : (i / (n - 1)) * w
      const y = h - (v / max) * h
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(" ")
  const area = `${line} L${w},${h} L0,${h} Z`
  return (
    <div className="flex items-stretch gap-2">
      <div className="flex flex-col justify-between py-0.5 font-mono text-[8px] tabular-nums text-neutral-600">
        <span>{compact(max)}</span>
        <span>0</span>
      </div>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        className="h-10 flex-1"
        aria-hidden
      >
        <line x1="0" y1={h - 1} x2={w} y2={h - 1} stroke="rgb(64 64 64 / 0.6)" strokeWidth={0.5} vectorEffect="non-scaling-stroke" />
        <path d={area} fill="rgb(56 189 248 / 0.14)" />
        <path
          d={line}
          fill="none"
          stroke="rgb(56 189 248 / 0.95)"
          strokeWidth={1.4}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  )
}

/** Default "world" mode of the right pane: totals + events sparkline +
 *  countries ranked by frequency (ACLED-style). Rows are clickable and lock
 *  the pane to that country's detail (#252). */
export function WorldStatusPanel() {
  const events = useEvents()
  const openCountry = useRightPaneModeStore((s) => s.openCountry)

  const stats = useMemo(() => worldStats(events), [events])
  const maxCount = stats.topCountries[0]?.count ?? 1

  return (
    <div className="flex h-full w-full flex-col gap-3 overflow-y-auto bg-neutral-950 p-3">
      {/* Totals + trend */}
      <section className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
        <h2 className="mb-3 text-[13px] font-semibold text-neutral-100">
          All events worldwide · <span className="text-emerald-400">live</span>
        </h2>
        <div className="flex items-end gap-2">
          <StatCell value={stats.total.toLocaleString()} label="Events" accent />
          <StatCell value={stats.activeCountries.toLocaleString()} label="Countries" />
          <StatCell value={stats.activeSources.toLocaleString()} label="Sources" />
        </div>
        <div className="mt-4">
          <span className="mb-1 block font-mono text-[9px] uppercase tracking-widest text-neutral-500">
            ↑ Events over time
          </span>
          <Sparkline points={stats.spark} />
        </div>
      </section>

      {/* Ranked countries */}
      <section className="flex min-h-0 flex-1 flex-col rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
        <h2 className="mb-3 text-[13px] font-semibold text-neutral-100">
          Highest frequency of events
        </h2>
        {stats.topCountries.length === 0 ? (
          <p className="py-6 text-center text-xs text-neutral-600">No events in view.</p>
        ) : (
          <ul className="-mx-2 flex-1 overflow-y-auto">
            {stats.topCountries.map(({ country, count }) => (
              <li key={country} className="border-b border-neutral-800/60 last:border-0">
                <button
                  type="button"
                  onClick={() => openCountry(country)}
                  className="flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left hover:bg-neutral-800/50"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`https://flagcdn.com/20x15/${country.toLowerCase()}.png`}
                    alt=""
                    width={20}
                    height={15}
                    className="shrink-0 rounded-[2px] border border-neutral-800"
                  />
                  <span className="w-24 shrink-0 text-[13px] leading-tight text-neutral-100">
                    {countryName(country)}
                  </span>
                  <span className="relative h-3 flex-1 overflow-hidden rounded-sm bg-neutral-800/60">
                    <span
                      className="absolute inset-y-0 left-0 rounded-sm bg-sky-600"
                      style={{ width: `${Math.max(3, (count / maxCount) * 100)}%` }}
                    />
                  </span>
                  <span className="w-12 shrink-0 text-right font-mono text-xs tabular-nums text-neutral-300">
                    {count.toLocaleString()}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
