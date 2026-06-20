"use client"

import { AlertTriangle, Loader2, RotateCcw } from "lucide-react"
import { cn } from "@/lib/utils"

export type PaneStatusMode = "loading" | "empty" | "error"

interface PaneStatusProps {
  mode: PaneStatusMode
  message?: string
  /** Empty state: a "Reset filters" button if provided. */
  onReset?: () => void
  className?: string
}

/**
 * Single overlay component for the loading / empty / error states each pane
 * can land in. Sits absolute-positioned over the canvas; markers + globe
 * stay mounted underneath so a re-fetch doesn't tear them out.
 */
export function PaneStatus({ mode, message, onReset, className }: PaneStatusProps) {
  if (mode === "loading") {
    return (
      <div
        role="status"
        aria-live="polite"
        className={cn(
          "pointer-events-none absolute inset-0 z-30 grid place-items-center bg-neutral-950/40 backdrop-blur-[1px]",
          className,
        )}
      >
        <div className="flex items-center gap-2 rounded-md border border-neutral-800 bg-neutral-950/80 px-3 py-2 font-mono text-[11px] uppercase tracking-widest text-neutral-300">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-neutral-500" />
          {message ?? "Loading events…"}
        </div>
      </div>
    )
  }

  if (mode === "error") {
    return (
      <div
        role="alert"
        className={cn(
          "absolute inset-x-0 top-0 z-30 mx-auto mt-2 w-fit max-w-[90%] rounded-md border border-red-900 bg-red-950/80 px-3 py-2 backdrop-blur-sm",
          className,
        )}
      >
        <div className="flex items-center gap-2 font-mono text-[11px] text-red-200">
          <AlertTriangle className="h-3.5 w-3.5" />
          <span className="uppercase tracking-widest">Error</span>
          <span className="text-red-100">{message ?? "Something went wrong."}</span>
        </div>
      </div>
    )
  }

  // mode === "empty"
  return (
    <div
      role="status"
      className={cn(
        "pointer-events-none absolute inset-0 z-20 grid place-items-center",
        className,
      )}
    >
      <div className="pointer-events-auto flex flex-col items-center gap-2 rounded-md border border-neutral-800 bg-neutral-950/80 px-4 py-3 backdrop-blur-sm">
        <p className="font-mono text-[11px] uppercase tracking-widest text-neutral-500">
          {message ?? "No events match the current filters"}
        </p>
        {onReset && (
          <button
            type="button"
            onClick={onReset}
            className="flex items-center gap-1.5 rounded border border-neutral-700 px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest text-neutral-300 hover:border-neutral-500 hover:text-neutral-100"
          >
            <RotateCcw className="h-3 w-3" />
            Reset filters
          </button>
        )}
      </div>
    </div>
  )
}
