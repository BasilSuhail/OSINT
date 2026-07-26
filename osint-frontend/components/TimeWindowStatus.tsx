"use client"

import { useEffect, useState } from "react"

import { describeTimeWindow, type TimeWindowState } from "@/lib/timeWindow"
import { cn } from "@/lib/utils"
import { DEFAULT_WINDOW_MS, type FilterStore } from "@/stores/createFilterStore"

/** How often the rendered "up to <time>" label is recomputed. The scrubber
 *  offset is relative to now, so a static label drifts as wall clock moves. */
const TICK_MS = 30_000

const STATE_CLASS: Record<TimeWindowState, string> = {
  live: "text-emerald-400",
  wide: "text-amber-400",
  historical: "text-amber-300",
}

const DOT_CLASS: Record<TimeWindowState, string> = {
  live: "bg-emerald-500",
  wide: "bg-amber-500",
  historical: "bg-amber-400",
}

interface TimeWindowStatusProps {
  useStore: FilterStore
}

/** Says, in the always-visible status bar, whether the map is showing now (#501).
 *
 * In the bar rather than over the map or in the filter rail: the rail can be
 * closed, and this has to be readable without opening anything. It sits beside
 * the connection indicator because "is the data live" and "is the view live"
 * are the same question asked of two different layers — a connected socket
 * feeding a map scrubbed three hours back is still not the current situation.
 */
export function TimeWindowStatus({ useStore }: TimeWindowStatusProps) {
  const windowEndOffsetMs = useStore((s) => s.windowEndOffsetMs)
  const windowLengthMs = useStore((s) => s.windowLengthMs)
  const setWindowEndOffset = useStore((s) => s.setWindowEndOffset)
  const setPlaying = useStore((s) => s.setPlaying)

  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => clearInterval(id)
  }, [])

  const view = describeTimeWindow({
    windowEndOffsetMs,
    windowLengthMs,
    defaultWindowMs: DEFAULT_WINDOW_MS,
    now,
  })

  const returnToNow = () => {
    setWindowEndOffset(0)
    // Playback walks the offset forward; leaving it running would scrub away
    // from now again the moment the user clicked to get back to it.
    setPlaying(false)
  }

  return (
    <span
      title={view.title}
      className="flex shrink-0 items-center gap-1 font-mono text-[8px] uppercase tracking-wide"
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", DOT_CLASS[view.state])} aria-hidden />
      <span className={STATE_CLASS[view.state]}>{view.label}</span>
      <span className="text-neutral-500">{view.detail}</span>
      {view.canReturnToNow && (
        <button
          type="button"
          onClick={returnToNow}
          className="rounded border border-amber-500/40 px-1 text-[8px] uppercase tracking-wide text-amber-300 transition-colors hover:bg-amber-500/15"
        >
          go live
        </button>
      )}
    </span>
  )
}
