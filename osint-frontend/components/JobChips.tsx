"use client"

import { useEffect, useState } from "react"
import useSWR from "swr"
import { fetchRecentJobs, type JobRun } from "@/lib/analytics"

const REFRESH_MS = 15_000
const STALL_MS = 10 * 60_000

/** Every job the stack can run — chips are always visible so the monitor is
 *  present even when everything is idle (#343). Power-LED semantics:
 *  green = working, red = idle/failed (failed says so and carries the error
 *  in its tooltip). CLI and beat variants collapse into one display name. */
const ROSTER = [
  "backfill-signals",
  "labels",
  "panel",
  "baselines",
  "coverage",
  "stories",
  "journal",
] as const

const DISPLAY_NAME: Record<string, string> = { "stories-cluster": "stories" }

type ChipState = "idle" | "working" | "stalled" | "failed"

interface Chip {
  name: string
  state: ChipState
  text: string | null
  tooltip: string
}

function deriveChips(runs: JobRun[], now: number): Chip[] {
  const newest = new Map<string, JobRun>()
  for (const run of runs) {
    const name = DISPLAY_NAME[run.job] ?? run.job
    const seen = newest.get(name)
    if (!seen || new Date(run.started_at) > new Date(seen.started_at)) newest.set(name, run)
  }

  return ROSTER.map((name) => {
    const run = newest.get(name)
    if (!run) {
      return { name, state: "idle" as const, text: null, tooltip: `${name}: never ran (48h)` }
    }
    if (run.status === "running") {
      const stalled = now - new Date(run.heartbeat_at).getTime() > STALL_MS
      if (stalled) {
        return {
          name,
          state: "stalled" as const,
          text: "stalled",
          tooltip: `${name}: no heartbeat for 10+ min — process likely died (${run.progress ?? "no progress recorded"})`,
        }
      }
      return {
        name,
        state: "working" as const,
        text: truncate(run.progress) ?? "working",
        tooltip: `${name}: ${run.progress ?? "running"}`,
      }
    }
    if (run.status === "failed") {
      return {
        name,
        state: "failed" as const,
        text: "failed",
        tooltip: `${name} failed ${ago(run.started_at, now)}: ${run.detail ?? "no detail"}`,
      }
    }
    return {
      name,
      state: "idle" as const,
      text: null,
      tooltip: `${name}: last run ${ago(run.started_at, now)}${run.progress ? ` — ${run.progress}` : ""}`,
    }
  })
}

function ago(iso: string, now: number): string {
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000))
  if (minutes < 60) return `${minutes}m ago`
  return `${Math.round(minutes / 60)}h ago`
}

function truncate(text: string | null): string | null {
  if (!text) return null
  return text.length > 30 ? `${text.slice(0, 29)}…` : text
}

const DOT: Record<ChipState, string> = {
  idle: "text-red-500/80",
  working: "animate-pulse text-emerald-400",
  stalled: "text-orange-400",
  failed: "text-red-400",
}

const TEXT: Record<ChipState, string> = {
  idle: "text-neutral-500",
  working: "text-emerald-300",
  stalled: "text-orange-400",
  failed: "text-red-400",
}

export function JobChips() {
  const { data } = useSWR("topbar-jobs", () => fetchRecentJobs(48), {
    refreshInterval: REFRESH_MS,
    revalidateOnFocus: false,
  })
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), REFRESH_MS)
    return () => clearInterval(timer)
  }, [])

  const chips = deriveChips(data ?? [], now)

  return (
    <>
      {chips.map((chip) => (
        <span
          key={chip.name}
          title={chip.tooltip}
          className="shrink-0 font-mono text-[8px] uppercase tracking-wide"
        >
          <span className={DOT[chip.state]}>●</span>{" "}
          <span className="text-neutral-200/90">{chip.name}</span>
          {chip.text ? <span className={TEXT[chip.state]}> {chip.text}</span> : null}
        </span>
      ))}
    </>
  )
}
