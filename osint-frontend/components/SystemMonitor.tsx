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
interface SystemMonitorProps {
  leading?: ReactNode
  /** Phone layout (#942): the cluster drops under the search bar, which owns
   *  the top strip there, and shows the worst band as a single dot rather
   *  than a count per band. The counts are the first thing the panel behind
   *  it says, and it is one tap away. */
  narrow?: boolean
}

export function SystemMonitor({ leading, narrow = false }: SystemMonitorProps) {
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
      className={
        "pointer-events-auto absolute right-3 z-50 flex flex-col items-end gap-2 " +
        //: On the search bar's own row on a phone, not under it (#944). Under
        //: it, the corner was a second strip across the top and the bar had to
        //: give up the width its own controls needed — the clear button went
        //: off the end of it. Beside it, the corner is a dot and the bar keeps
        //: everything except the forty pixels this occupies.
        (narrow ? "top-[calc(env(safe-area-inset-top)+1.5rem)]" : "top-3")
      }
    >
      {/*: One box, not two (#938). "Is the view live" and "are the sources
          live" are the same question asked of two layers, and two bordered
          pills side by side made them look like two unrelated readouts. The
          border lives on this shell so the time readout can keep its own
          `go live` button — a button inside a button is invalid, which is what
          kept these apart. */}
      <div
        className={
          "flex items-center rounded-xl border bg-neutral-950/90 shadow-lg shadow-black/40 backdrop-blur-xl transition-colors " +
          (narrow ? "gap-1 px-1.5 py-1 " : "gap-2 px-2.5 py-1.5 ") +
          (open ? "border-neutral-600" : "border-neutral-800")
        }
      >
        {/*: The word, then whether the view is live, then how many sources are
            in trouble — read left to right it is one sentence about one
            system. Two toggles rather than one wrapping the lot: the readout
            between them carries `go live`, and a button cannot contain one. */}
        {/*: The word goes on a phone (#944). Seven letters at a quarter-em of
            tracking is most of what the corner costs, and it names the panel
            rather than saying anything about it — the dots beside it are the
            reading, and they are their own button into the same panel. */}
        {!narrow && (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-label="System monitor"
            className={
              "rounded-md px-1 py-0.5 font-mono text-[8px] uppercase tracking-[0.24em] transition-colors " +
              (open ? "text-neutral-200" : "text-neutral-400 hover:text-neutral-200")
            }
          >
            system
          </button>
        )}
        {leading}
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label="Source health"
          className={
            "flex items-center rounded-md transition-colors " +
            (narrow ? "gap-1 px-0.5 " : "gap-2 px-1 py-0.5 ") +
            (open ? "text-neutral-200" : "text-neutral-400 hover:text-neutral-200")
          }
        >
          {counts.length === 0 ? (
            <span className="font-mono text-[10px] leading-none text-emerald-400">✓</span>
          ) : (
            <span className="flex items-center gap-1.5">
              {/*: Worst band only on a phone (#942). `attentionCounts` is
                  ordered worst first, and the corner there is competing with
                  a search bar for a strip 390px wide — the other bands are
                  the first thing the panel behind this says. */}
              {(narrow ? counts.slice(0, 1) : counts).map(({ band, count }) => (
                <span
                  key={band}
                  className="flex items-center gap-0.5 font-mono text-[9px] leading-none"
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
