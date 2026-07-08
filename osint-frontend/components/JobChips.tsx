"use client"

import { useEffect, useState } from "react"
import useSWR from "swr"
import { fetchRecentJobs, type JobRun } from "@/lib/analytics"

const REFRESH_MS = 15_000
const STALL_MS = 10 * 60_000
const FAILED_WINDOW_MS = 24 * 60 * 60_000

type Live = { run: JobRun; stalled: boolean }

/** Activity monitor (#341): running jobs pulse with live progress, a crashed
 *  job (stale heartbeat) reads as stalled, and failures from the last 24h
 *  stay visible until they scroll out of the window. */
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
  const runs = data ?? []

  // One chip per job name — newest run wins.
  const newestByJob = new Map<string, JobRun>()
  for (const run of runs) if (!newestByJob.has(run.job)) newestByJob.set(run.job, run)

  const live: Live[] = []
  let failed = 0
  let lastFailed: JobRun | null = null
  for (const run of newestByJob.values()) {
    if (run.status === "running") {
      live.push({ run, stalled: now - new Date(run.heartbeat_at).getTime() > STALL_MS })
    } else if (run.status === "failed" && now - new Date(run.started_at).getTime() < FAILED_WINDOW_MS) {
      failed += 1
      if (!lastFailed) lastFailed = run
    }
  }

  if (live.length === 0 && failed === 0) return null

  return (
    <>
      {live.map(({ run, stalled }) => (
        <span
          key={run.job}
          title={
            stalled
              ? `${run.job}: no heartbeat for 10+ min — process likely died (${run.progress ?? "no progress recorded"})`
              : `${run.job}: ${run.progress ?? "running"}`
          }
          className="shrink-0 font-mono text-[8px] uppercase tracking-wide text-neutral-400"
        >
          <span className={stalled ? "text-orange-400" : "animate-pulse text-cyan-400"}>
            {stalled ? "◼" : "▶"}
          </span>{" "}
          <span className="text-neutral-200/80">{run.job}</span>{" "}
          <span className={stalled ? "text-orange-400" : "text-neutral-500"}>
            {stalled ? "stalled" : truncate(run.progress) ?? "running"}
          </span>
        </span>
      ))}
      {failed > 0 && lastFailed ? (
        <span
          title={`${lastFailed.job} failed: ${lastFailed.detail ?? "no detail"}`}
          className="shrink-0 font-mono text-[8px] uppercase tracking-wide"
        >
          <span className="text-red-400">
            {failed} job{failed > 1 ? "s" : ""} failed
          </span>
        </span>
      ) : null}
    </>
  )
}

function truncate(text: string | null): string | null {
  if (!text) return null
  return text.length > 28 ? `${text.slice(0, 27)}…` : text
}
