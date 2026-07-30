"use client"

import { X } from "lucide-react"
import { useEffect } from "react"
import { useWorldDetailStore } from "@/stores/worldDetailStore"
import { WorldStatusPanel } from "../WorldStatusPanel"
import { BriefingPanel } from "./BriefingPanel"
import { CoveragePanel } from "./CoveragePanel"

/**
 * What the world tile's graph opens (#705).
 *
 * Ranked countries, the coverage table and the briefing — the same content the
 * deck's expand control shows, in the slot the story detail already uses. The
 * tile keeps its graph and stories summary; this sits next to it rather than
 * over it.
 *
 * Coverage lives here rather than on its own tile because it is a per-country
 * view: it belongs behind the country door, not beside it.
 */
export function WorldDetailCard() {
  const closeWorld = useWorldDetailStore((s) => s.closeWorld)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeWorld()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [closeWorld])

  return (
    <div className="flex h-full w-full flex-col bg-neutral-950">
      <div className="flex h-8 shrink-0 items-center justify-between px-3">
        <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-400">
          world — detail
        </span>
        <button
          type="button"
          onClick={closeWorld}
          aria-label="Close world detail"
          className="text-neutral-500 transition-colors hover:text-neutral-200"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="h-[55vh]">
          <WorldStatusPanel />
        </div>
        <div className="flex flex-col gap-6 p-3">
          <CoveragePanel />
          <BriefingPanel />
        </div>
      </div>
    </div>
  )
}
