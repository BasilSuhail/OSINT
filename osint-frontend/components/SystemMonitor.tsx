"use client"

import { useEffect, useRef, useState, type ReactNode } from "react"
import useSWR from "swr"

import {
  fetchBrainNarrative,
  fetchIngestHealth,
  fetchSourceCoverage,
  isApiConfigured,
} from "@/lib/apiClient"
import { fetchRecentJobs } from "@/lib/analytics"
import { summarizeSystemHealth, type HealthBand } from "@/lib/systemHealth"
import { attentionCounts } from "@/lib/systemMonitor"
import { SystemMonitorPanel } from "./SystemMonitorPanel"

const HEALTH_REFRESH_MS = 30_000
const COVERAGE_REFRESH_MS = 60_000
const BRAIN_REFRESH_MS = 30_000
const JOBS_REFRESH_MS = 15_000
/** Older than this and the brain is resting rather than reading. */
const BRAIN_STALE_MS = 40 * 60_000

export const BAND_DOT: Record<HealthBand, string> = {
  offline: "text-red-500",
  warn: "text-amber-400",
  stale: "text-orange-400",
  ok: "text-emerald-400",
}

/**
 * One button in the corner, and the monitor behind it (#936).
 *
 * The bar this replaces showed eleven chips at all times. Eleven permanent
 * warnings are read once and then stop being read at all, and they cost the
 * map the full width of the screen to say so. What the corner needs to carry
 * is smaller than that: how many sources are in trouble, and how badly. Three
 * numbers answer it. The words for each band, the per-source ages, the jobs
 * and the brain all live one click away, where there is room to lay them out
 * rather than abbreviate them into chips.
 */
export function SystemMonitor({ leading }: { leading?: ReactNode }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  const { data: ingestRows } = useSWR(
    isApiConfigured ? "monitor-ingest-health" : null,
    () => fetchIngestHealth(7),
    { refreshInterval: HEALTH_REFRESH_MS, revalidateOnFocus: false },
  )
  const { data: coverageRows } = useSWR(
    isApiConfigured ? "monitor-source-coverage" : null,
    () => fetchSourceCoverage(30),
    { refreshInterval: COVERAGE_REFRESH_MS, revalidateOnFocus: false },
  )
  const { data: brain } = useSWR(
    isApiConfigured ? "monitor-brain-narrative" : null,
    fetchBrainNarrative,
    { refreshInterval: BRAIN_REFRESH_MS, revalidateOnFocus: false },
  )
  //: Jobs poll only while the panel is open. A closed panel showing three
  //: numbers has no use for a fifteen-second job roster, and the request runs
  //: for the whole session otherwise.
  const { data: jobRuns } = useSWR(
    open && isApiConfigured ? "monitor-jobs" : null,
    () => fetchRecentJobs(48),
    { refreshInterval: JOBS_REFRESH_MS, revalidateOnFocus: false },
  )

  const datasets = summarizeSystemHealth(ingestRows ?? [], coverageRows ?? [])
  const counts = attentionCounts(datasets)

  const createdAtMs = brain?.created_at ? new Date(brain.created_at).getTime() : null
  const brainResting =
    !brain?.present ||
    createdAtMs == null ||
    !Number.isFinite(createdAtMs) ||
    Date.now() - createdAtMs > BRAIN_STALE_MS

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false)
    }
    //: Clicking the map should put the panel away. Anything inside the corner
    //: — the button included — is handled by its own click, so the check is on
    //: the whole cluster rather than the panel alone.
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    window.addEventListener("keydown", onKeyDown)
    window.addEventListener("pointerdown", onPointerDown)
    return () => {
      window.removeEventListener("keydown", onKeyDown)
      window.removeEventListener("pointerdown", onPointerDown)
    }
  }, [open])

  return (
    <div
      ref={rootRef}
      className="pointer-events-auto absolute right-3 top-3 z-50 flex flex-col items-end gap-2"
    >
      <div className="flex items-center gap-2">
        {leading}
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label="System monitor"
          className={
            "flex items-center gap-2.5 rounded-xl border bg-neutral-950/90 px-3 py-2 shadow-lg shadow-black/40 backdrop-blur-xl transition-colors " +
            (open
              ? "border-neutral-600 text-neutral-200"
              : "border-neutral-800 text-neutral-400 hover:border-neutral-700 hover:text-neutral-200")
          }
        >
          <span className="font-mono text-[9px] uppercase tracking-[0.24em]">system</span>
          {counts.length === 0 ? (
            <span className="font-mono text-[11px] leading-none text-emerald-400">✓</span>
          ) : (
            <span className="flex items-center gap-2">
              {counts.map(({ band, count }) => (
                <span
                  key={band}
                  className="flex items-center gap-1 font-mono text-[10px] leading-none"
                >
                  <span className={BAND_DOT[band]}>●</span>
                  <span className="text-neutral-300">{count}</span>
                </span>
              ))}
            </span>
          )}
        </button>
      </div>

      {open ? (
        <SystemMonitorPanel
          datasets={datasets}
          ingestRows={ingestRows ?? []}
          coverageRows={coverageRows ?? []}
          jobRuns={jobRuns ?? []}
          brainResting={brainResting}
          brainSummary={brain?.payload?.system ?? null}
          brainModel={brain?.model ?? null}
          brainCreatedAt={brain?.created_at ?? null}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </div>
  )
}
