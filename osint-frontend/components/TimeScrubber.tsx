"use client"

import { ChevronDown, ChevronUp, Pause, Play } from "lucide-react"
import { useState } from "react"
import { format } from "date-fns"
import { WINDOW_SPAN_MS, type FilterStore } from "@/stores/createFilterStore"
import { LIVE_TOLERANCE_MS } from "@/lib/timeWindow"
import { cn } from "@/lib/utils"
import { Slider } from "@/components/ui/slider"

const SPEEDS: { label: string; value: number }[] = [
  { label: "1×", value: 1 },
  { label: "10×", value: 10 },
  { label: "100×", value: 100 },
  { label: "MAX", value: 10_000 },
]

interface TimeScrubberProps {
  useStore: FilterStore
  windowEnd: number
  /** Whether the filter panel is showing. It is docked to the right edge and
   *  runs the full height of the map, so the bar stops short of it rather
   *  than sliding underneath. */
  panelOpen: boolean
}

export function TimeScrubber({ useStore, windowEnd, panelOpen }: TimeScrubberProps) {
  const playing = useStore((s) => s.playing)
  const speed = useStore((s) => s.speed)
  const windowEndOffsetMs = useStore((s) => s.windowEndOffsetMs)
  const windowLengthMs = useStore((s) => s.windowLengthMs)
  const togglePlaying = useStore((s) => s.togglePlaying)
  const setSpeed = useStore((s) => s.setSpeed)
  const setWindowEndOffset = useStore((s) => s.setWindowEndOffset)

  // Slider value: SPAN - offset, so the right edge = live (offset 0).
  const sliderValue = WINDOW_SPAN_MS - windowEndOffsetMs
  // Same threshold the status bar uses (#501) — two indicators disagreeing
  // about whether the view is live is worse than having only one.
  const isLive = windowEndOffsetMs < LIVE_TOLERANCE_MS

  const windowStart = windowEnd - windowLengthMs

  //: The scrubber owns a strip of the map's bottom edge, and the map goes on
  //: under it. Minimised it becomes the same handle the deck and the filter
  //: rail use — one shape for "put this away", turned to face the edge it sits
  //: on. Playback state is untouched by hiding it: this is what is on screen,
  //: not what the console is doing.
  const [hidden, setHidden] = useState(false)

  //: The deck's handle, turned to face the bottom edge: it floats on the map
  //: *outside* the bar, never inside it, centred on the span the bar occupies
  //: and sitting on its top edge. It keeps that one spot whether the bar is up
  //: or down, so the control that brings the bar back is never somewhere new.
  //: Square corners against the bar it moves, round corners toward the map,
  //: and the arrow points the way the bar will go.
  return (
    <div
      className={cn(
        "pointer-events-none absolute bottom-3 left-[calc(var(--panel-width,0px)+1.5rem)] z-20 h-11",
        panelOpen ? "right-[21.25rem]" : "right-20",
      )}
    >
      <button
        type="button"
        onClick={() => setHidden(!hidden)}
        title={hidden ? "Show the time scrubber" : "Hide the time scrubber"}
        aria-label={hidden ? "Show the time scrubber" : "Hide the time scrubber"}
        aria-expanded={!hidden}
        className="pointer-events-auto absolute bottom-full left-1/2 grid -translate-x-1/2 place-items-center rounded-t-xl rounded-b-md border border-white/10 bg-neutral-950/85 px-6 py-1.5 text-neutral-400 shadow-2xl shadow-black/60 backdrop-blur-xl transition-colors hover:text-neutral-100"
      >
        {hidden ? <ChevronUp size={16} aria-hidden /> : <ChevronDown size={16} aria-hidden />}
      </button>

      {!hidden && (
        <div className="pointer-events-auto flex h-full min-h-[44px] items-center gap-3 rounded-2xl border border-white/10 bg-neutral-950/85 px-3 shadow-2xl shadow-black/60 backdrop-blur-xl">
          <button
            type="button"
            onClick={togglePlaying}
            aria-label={playing ? "Pause" : "Play"}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-neutral-700 bg-neutral-900 text-neutral-200 transition-colors hover:bg-neutral-800"
          >
            {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </button>

          <div className="flex shrink-0 items-center gap-1">
            {SPEEDS.map((s) => (
              <button
                key={s.value}
                type="button"
                onClick={() => setSpeed(s.value)}
                className={cn(
                  "rounded px-1.5 py-1 font-mono text-[11px] transition-colors",
                  speed === s.value
                    ? "bg-emerald-500/20 text-emerald-300"
                    : "text-neutral-500 hover:text-neutral-200",
                )}
              >
                {s.label}
              </button>
            ))}
          </div>

          <div className="flex min-w-0 flex-1 items-center gap-3">
            <Slider
              value={[sliderValue]}
              min={0}
              max={WINDOW_SPAN_MS}
              step={60_000}
              onValueChange={(v) => setWindowEndOffset(WINDOW_SPAN_MS - (Array.isArray(v) ? v[0] : v))}
              aria-label="Time window"
              className="flex-1"
            />
          </div>

          <div className="flex shrink-0 flex-col items-end font-mono leading-tight">
            <span className="text-[11px] text-neutral-200">
              {format(windowStart, "MMM d HH:mm")} → {format(windowEnd, "MMM d HH:mm")}
            </span>
            <span
              className={cn(
                "text-[10px] uppercase tracking-widest",
                isLive ? "text-emerald-400" : "text-amber-400",
              )}
            >
              {isLive ? "● live" : "○ scrubbing"}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
