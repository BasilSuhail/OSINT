"use client"

import { useEffect, useState } from "react"
import { Globe2, LayoutList } from "lucide-react"
import type { VisibleEvent } from "@/lib/queries"
import type { FilterStore } from "@/stores/createFilterStore"
import { rightPaneMode, useRightPaneModeStore } from "@/stores/rightPaneModeStore"
import { ClusterListPanel } from "./ClusterListPanel"
import { CountrySidePanel } from "./CountrySidePanel"
import { EventDetailCard } from "./EventDetailCard"
import { GlobePane } from "./GlobePane"
import { WorldStatusPanel } from "./WorldStatusPanel"

interface RightPaneProps {
  useStore: FilterStore
  railOpen: boolean
  onRailOpenChange: (open: boolean) => void
  onCount: (n: number) => void
  onSelectEvent: (ev: VisibleEvent) => void
}

/** The right pane is a swappable multi-window surface (#252):
 *  - world  → ACLED-style world status panel (default)
 *  - globe  → the 3D globe, exactly as before
 *  - entity → a clicked country / event, locked until Esc / ×
 *
 *  The globe is expensive (react-globe.gl + three), so once shown it stays
 *  mounted and is merely hidden behind the other modes — swapping is instant
 *  and never churns the WebGL context. */
export function RightPane({
  useStore,
  railOpen,
  onRailOpenChange,
  onCount,
  onSelectEvent,
}: RightPaneProps) {
  const base = useRightPaneModeStore((s) => s.base)
  const entity = useRightPaneModeStore((s) => s.entity)
  const swapBase = useRightPaneModeStore((s) => s.swapBase)
  const closeEntity = useRightPaneModeStore((s) => s.closeEntity)
  const openCountry = useRightPaneModeStore((s) => s.openCountry)
  const openEvent = useRightPaneModeStore((s) => s.openEvent)

  const mode = rightPaneMode(base, entity)

  // Lazy-mount the globe on first request, then keep it warm. Converge during
  // render (React's blessed pattern) rather than in an effect.
  const [globeMounted, setGlobeMounted] = useState(base === "globe")
  if (base === "globe" && !globeMounted) setGlobeMounted(true)

  // Esc closes a locked entity and restores the base mode.
  useEffect(() => {
    if (!entity) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeEntity()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [entity, closeEntity])

  return (
    <div className="relative h-full w-full overflow-hidden bg-neutral-950">
      {/* Globe — mounted once, kept warm, hidden behind other modes. */}
      {globeMounted && (
        <div
          className="absolute inset-0"
          style={{ visibility: mode === "globe" ? "visible" : "hidden" }}
          aria-hidden={mode !== "globe"}
        >
          <GlobePane
            useStore={useStore}
            railOpen={railOpen}
            onRailOpenChange={onRailOpenChange}
            onCount={onCount}
            onSelectEvent={onSelectEvent}
            active={mode === "globe"}
          />
        </div>
      )}

      {/* World status (default). */}
      {mode === "world" && (
        <div className="absolute inset-0">
          <WorldStatusPanel />
        </div>
      )}

      {/* Locked entity detail. */}
      {mode === "entity" && entity && (
        <div className="absolute inset-0 overflow-y-auto bg-neutral-950 p-3">
          {entity.kind === "country" ? (
            <CountrySidePanel country={entity.iso} onClose={closeEntity} />
          ) : entity.kind === "cluster" ? (
            <ClusterListPanel
              label={entity.label}
              events={entity.events}
              onSelectEvent={openEvent}
              onClose={closeEntity}
            />
          ) : (
            <EventDetailCard
              event={entity.event}
              embedded
              onClose={closeEntity}
              onSelectCountry={(iso) => openCountry(iso)}
            />
          )}
        </div>
      )}

      {/* Swap toggle (world ⇄ globe) — hidden while an entity is locked. */}
      {mode !== "entity" && (
        <button
          type="button"
          onClick={swapBase}
          className="absolute right-2 top-2 z-40 flex items-center gap-1.5 rounded-md border border-neutral-700 bg-neutral-950/85 px-2.5 py-1 font-mono text-[10px] uppercase tracking-widest text-neutral-300 backdrop-blur-sm transition-colors hover:border-cyan-500/60 hover:text-cyan-300"
          aria-label={mode === "globe" ? "Show world status" : "Show globe"}
        >
          {mode === "globe" ? (
            <>
              <LayoutList className="h-3 w-3" /> status
            </>
          ) : (
            <>
              <Globe2 className="h-3 w-3" /> globe
            </>
          )}
        </button>
      )}
    </div>
  )
}
