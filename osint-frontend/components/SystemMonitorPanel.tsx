"use client"

import { useState } from "react"

import type { JobRun } from "@/lib/analytics"
import { deriveJobStatuses, groupJobs, type JobState } from "@/lib/jobStatus"
import type { DatasetHealthSummary } from "@/lib/systemHealth"
import {
  formatAge,
  groupByBand,
  insertedByDay,
  sparklinePoints,
  totalRecentRows,
} from "@/lib/systemMonitor"
import type { IngestHealthRow, SourceCoverageRow } from "@/lib/types"
import { ConnectionIndicator } from "./ConnectionIndicator"
import { BAND_DOT } from "./SystemMonitor"

const JOB_DOT: Record<JobState, string> = {
  failed: "text-red-500",
  stalled: "text-orange-400",
  working: "text-emerald-400",
  idle: "text-neutral-600",
}

type Tab = "sources" | "jobs" | "brain"
const TABS: Tab[] = ["sources", "jobs", "brain"]

/** One coloured header per group, then its rows. Said once, at the top of the
 *  group, so the colour is explained rather than merely repeated. */
function GroupHeader({ dot, label, count }: { dot: string; label: string; count: number }) {
  return (
    <div className="flex items-baseline gap-2 pb-1 pt-3 font-mono text-[9px] uppercase tracking-[0.2em] first:pt-0">
      <span className={dot}>●</span>
      <span className="text-neutral-300">{label}</span>
      <span className="ml-auto text-neutral-500">{count}</span>
    </div>
  )
}

/** A source row that opens in place. The band already said "stale"; the row
 *  says how long, and the expansion says what the ingest run actually saw. */
function SourceRow({ dataset, nowMs }: { dataset: DatasetHealthSummary; nowMs: number }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-t border-neutral-800/60 first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-baseline gap-3 py-1.5 text-left"
      >
        <span className="min-w-0 flex-1 truncate text-[12px] text-neutral-200">
          {dataset.label}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-neutral-500">
          {dataset.healthy}/{dataset.total} feeds
        </span>
        <span className="w-16 shrink-0 text-right font-mono text-[10px] text-neutral-400">
          {formatAge(dataset.latestIso, nowMs)}
        </span>
      </button>
      {open ? (
        <p className="pb-2 pl-1 pr-1 text-[11px] leading-snug text-neutral-500">
          {dataset.detail || "No ingest detail recorded."}
        </p>
      ) : null}
    </div>
  )
}

/** Rows written per day across every source. The footer answers the one
 *  question no per-source row can: is anything still arriving at all. */
function IngestSparkline({ rows }: { rows: IngestHealthRow[] }) {
  const days = insertedByDay(rows)
  const points = sparklinePoints(days)
  const total = days.reduce((sum, day) => sum + day.inserted, 0)

  return (
    <div className="flex items-center gap-3 border-t border-neutral-800 px-3 py-2">
      <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.2em] text-neutral-500">
        inserted · {days.length}d
      </span>
      {points.length > 0 ? (
        <svg
          viewBox="0 0 100 20"
          preserveAspectRatio="none"
          className="h-5 min-w-0 flex-1"
          aria-hidden
        >
          <polyline
            points={points.map((p) => `${p.x * 100},${p.y * 18 + 1}`).join(" ")}
            fill="none"
            stroke="currentColor"
            strokeWidth={1}
            vectorEffect="non-scaling-stroke"
            className="text-cyan-400/70"
          />
        </svg>
      ) : (
        //: Not a flat line pinned to the floor — that reads as a measurement
        //: when it is the absence of one.
        <span className="min-w-0 flex-1 font-mono text-[10px] text-neutral-600">
          nothing written
        </span>
      )}
      <span className="shrink-0 font-mono text-[10px] text-neutral-400">
        {total.toLocaleString()}
      </span>
    </div>
  )
}

interface SystemMonitorPanelProps {
  datasets: DatasetHealthSummary[]
  ingestRows: IngestHealthRow[]
  coverageRows: SourceCoverageRow[]
  jobRuns: JobRun[]
  brainResting: boolean
  brainSummary: string | null
  brainModel: string | null
  brainCreatedAt: string | null
  onClose: () => void
}

/**
 * The monitor itself (#936): a floating window in the shape of a desktop
 * activity monitor — title, tabs, grouped rows, footer graph.
 *
 * Everything the status bar used to shout from the top of the screen is here,
 * and here it can be laid out rather than abbreviated: a source gets its age
 * and its ingest detail, a job gets its failure reason, the brain gets the
 * sentence it wrote. None of it competes with the map for space, because none
 * of it is on screen until asked for.
 */
export function SystemMonitorPanel({
  datasets,
  ingestRows,
  coverageRows,
  jobRuns,
  brainResting,
  brainSummary,
  brainModel,
  brainCreatedAt,
  onClose,
}: SystemMonitorPanelProps) {
  const [tab, setTab] = useState<Tab>("sources")
  const nowMs = Date.now()
  const bands = groupByBand(datasets)
  const jobGroups = groupJobs(deriveJobStatuses(jobRuns, nowMs))
  const recentRows = totalRecentRows(coverageRows)

  return (
    <div className="w-[min(26rem,calc(100vw-1.5rem))] overflow-hidden rounded-2xl border border-neutral-800 bg-neutral-950/97 shadow-2xl shadow-black/50 backdrop-blur-xl">
      <div className="flex items-center gap-2 border-b border-neutral-800 px-3 py-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.24em] text-neutral-300">
          system
        </span>
        <ConnectionIndicator />
        <span className="ml-auto font-mono text-[9px] text-neutral-500">
          {datasets.length} sources · {recentRows.toLocaleString()} rows · 30d
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close the system monitor"
          className="ml-1 font-mono text-[11px] leading-none text-neutral-500 hover:text-neutral-200"
        >
          ✕
        </button>
      </div>

      <div className="flex border-b border-neutral-800">
        {TABS.map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => setTab(name)}
            className={
              "px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.2em] transition-colors " +
              (tab === name
                ? "border-b border-cyan-400/70 text-neutral-100"
                : "text-neutral-500 hover:text-neutral-300")
            }
          >
            {name}
          </button>
        ))}
      </div>

      <div className="max-h-[60vh] overflow-y-auto px-3 pb-2">
        {tab === "sources" ? (
          bands.length === 0 ? (
            <p className="py-4 text-[12px] text-neutral-500">No ingest health reported yet.</p>
          ) : (
            bands.map((group) => (
              <div key={group.band}>
                <GroupHeader dot={BAND_DOT[group.band]} label={group.label} count={group.count} />
                {group.datasets.map((dataset) => (
                  <SourceRow key={dataset.key} dataset={dataset} nowMs={nowMs} />
                ))}
              </div>
            ))
          )
        ) : null}

        {tab === "jobs"
          ? jobGroups.map((group) => (
              <div key={group.state}>
                <GroupHeader dot={JOB_DOT[group.state]} label={group.label} count={group.count} />
                {group.jobs.map((job) => (
                  <div
                    key={job.name}
                    className="border-t border-neutral-800/60 py-1.5 first:border-t-0"
                  >
                    <div className="flex items-baseline gap-3">
                      <span className="min-w-0 flex-1 truncate text-[12px] text-neutral-200">
                        {job.name}
                      </span>
                      <span className="w-20 shrink-0 text-right font-mono text-[10px] text-neutral-400">
                        {job.age}
                      </span>
                    </div>
                    <p className="text-[11px] leading-snug text-neutral-500">{job.detail}</p>
                  </div>
                ))}
              </div>
            ))
          : null}

        {tab === "brain" ? (
          <div className="py-3">
            <div className="flex items-baseline gap-2 font-mono text-[9px] uppercase tracking-[0.2em]">
              <span className={brainResting ? "text-amber-400" : "text-emerald-400"}>●</span>
              <span className="text-neutral-300">{brainResting ? "resting" : "working"}</span>
              {brainModel ? <span className="ml-auto text-neutral-600">{brainModel}</span> : null}
            </div>
            <p className="mt-2 text-[12px] leading-relaxed text-neutral-400">
              {brainResting
                ? "The box is busy or no read is ready yet."
                : (brainSummary ?? "No pipeline summary in the latest read.")}
            </p>
            <p className="mt-2 font-mono text-[10px] text-neutral-600">
              {brainCreatedAt
                ? `last read ${new Date(brainCreatedAt).toLocaleTimeString()}`
                : "no read recorded"}
            </p>
          </div>
        ) : null}
      </div>

      <IngestSparkline rows={ingestRows} />
    </div>
  )
}
