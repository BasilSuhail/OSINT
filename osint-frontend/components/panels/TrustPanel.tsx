"use client"

import React from "react"
import useSWR from "swr"
import { fetchConsoleHealth, type ConsoleHealth } from "@/lib/analytics"
import { BarRow, Hint, StatTile } from "./viz"

const REFRESH_MS = 60_000

/** How long a silence has to run before it is worth a colour.
 *
 *  Judged against the source's own cadence rather than a fixed clock: a
 *  fifteen-minute feed missing an hour and a monthly archive missing an hour
 *  are not the same event. */
function silenceTone(minutes: number | null, cadence: number): string {
  if (minutes === null) return "text-red-400"
  if (cadence > 0 && minutes > cadence * 24) return "text-red-400"
  return "text-amber-300"
}

function humanMinutes(minutes: number | null): string {
  if (minutes === null) return "never"
  if (minutes < 90) return `${minutes} min`
  if (minutes < 60 * 48) return `${Math.round(minutes / 60)} h`
  return `${Math.round(minutes / 1440)} d`
}

/** Fraction of drawn rows standing on a place somebody verified. */
function exactShare(precision: ConsoleHealth["precision"]): number | null {
  const total = Object.values(precision).reduce((sum, n) => sum + n, 0)
  return total ? (precision.exact ?? 0) / total : null
}

export function TrustPanel() {
  const { data, error } = useSWR<ConsoleHealth>("console-health", fetchConsoleHealth, {
    refreshInterval: REFRESH_MS,
  })

  if (error) {
    return (
      <p className="px-4 py-3 font-mono text-[10px] text-red-400">
        health unavailable — the panel that says whether to trust the console cannot itself
        be reached
      </p>
    )
  }
  if (!data) {
    return <p className="px-4 py-3 font-mono text-[10px] text-neutral-500">measuring…</p>
  }

  const exact = exactShare(data.precision)
  const biggest = data.composition[0]
  const audited = data.audit.ran_at
  const newsClass = data.composition.find((c) => c.name === "news")

  return (
    <div className="space-y-4 px-4 py-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatTile
          value={data.silent.length + data.rested.length}
          label="sources not reporting"
          tone={data.silent.length + data.rested.length ? "text-amber-300" : "text-neutral-200"}
          hint="Feeds past their own cadence, plus feeds the quarantine is resting. Both are silence; only one of them is a surprise."
        />
        <StatTile
          value={exact === null ? "—" : `${Math.round(exact * 100)}%`}
          label="pins actually verified"
          tone={exact !== null && exact < 0.25 ? "text-amber-300" : "text-neutral-200"}
          hint="Share of drawn rows standing on a place somebody verified. The rest are city, area or country centroids — real evidence, but not the street."
        />
        <StatTile
          value={audited ? data.audit.findings_total : "never"}
          label="audit findings"
          tone={audited ? "text-neutral-200" : "text-red-400"}
          hint="From the last stored audit run. 'Never' means the audit has not run — which is not the same as clean, and is the more worrying of the two."
        />
        <StatTile
          value={newsClass ? `${Math.round(newsClass.share * 100)}%` : "—"}
          label="of arrivals are news"
          hint="What the corpus is actually made of. Sensor feeds outnumber news by orders of magnitude, so any count that does not segment by source is a sensor counter wearing a news label."
        />
      </div>

      <section>
        <h3 className="mb-1 font-mono text-[9px] uppercase tracking-wider text-neutral-500">
          <Hint term="not reporting">
            A source is silent when it has missed its own cadence by the watchdog&apos;s
            margin. &quot;Never&quot; means no successful fetch is on record at all — a
            different problem from a feed that stopped this morning.
          </Hint>
        </h3>
        {data.silent.length === 0 && data.rested.length === 0 ? (
          <p className="font-mono text-[10px] text-neutral-400">
            every source is reporting within its cadence
          </p>
        ) : (
          <ul className="space-y-0.5">
            {data.silent.map((s) => (
              <li key={s.source} className="flex justify-between font-mono text-[10px]">
                <span className="text-neutral-300">{s.source}</span>
                <span className={silenceTone(s.minutes_silent, s.cadence_minutes)}>
                  silent {humanMinutes(s.minutes_silent)}
                </span>
              </li>
            ))}
            {data.rested.map((r) => (
              <li key={r.source} className="flex justify-between font-mono text-[10px]">
                <span className="text-neutral-300">{r.source}</span>
                <span className="text-neutral-500">
                  rested · {r.http_status ?? r.kind} · until {r.retry_after.slice(5, 16)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="mb-1 font-mono text-[9px] uppercase tracking-wider text-neutral-500">
          <Hint term="what arrived, by class">
            Counted on arrival rather than on when the event happened: a monthly archive
            ingested this morning carries rows dated two months back, and an occurrence
            window would report it as contributing nothing.
          </Hint>
        </h3>
        <div className="space-y-0.5">
          {data.composition.map((c) => (
            <BarRow
              key={c.name}
              label={`${c.name} · newest ${humanMinutes(c.newest_age_minutes)} old`}
              value={c.rows.toLocaleString()}
              fraction={biggest && biggest.rows ? c.rows / biggest.rows : 0}
              emphasis={c.name === "news"}
            />
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-1 font-mono text-[9px] uppercase tracking-wider text-neutral-500">
          <Hint term="what the pins claim">
            Every drawn coordinate makes a claim about how precisely it is known. A verified
            venue and a country centroid are both legitimate and are not the same statement.
          </Hint>
        </h3>
        <div className="space-y-0.5">
          {Object.entries(data.precision).map(([kind, n]) => (
            <BarRow
              key={kind}
              label={kind}
              value={String(n)}
              fraction={n / Math.max(...Object.values(data.precision), 1)}
              barClass={kind === "exact" ? "bg-emerald-400/80" : "bg-neutral-500/60"}
              emphasis={kind === "exact"}
            />
          ))}
        </div>
      </section>

      <p className="font-mono text-[9px] text-neutral-600">
        measured {data.generated_at.slice(11, 16)} UTC
        {audited ? ` · audit ran ${audited.slice(5, 16)}` : " · audit has never run"}
      </p>
    </div>
  )
}
