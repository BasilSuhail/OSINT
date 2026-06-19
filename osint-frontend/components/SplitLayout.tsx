"use client"

import dynamic from "next/dynamic"
import { useCallback, useEffect, useState } from "react"
import { format } from "date-fns"
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from "react-resizable-panels"
import { useConfigured, useEvents } from "@/app/providers"
import { SOURCE_FILTERS } from "@/lib/types"
import { useLeftPaneStore } from "@/stores/leftPaneStore"
import { useRightPaneStore } from "@/stores/rightPaneStore"
import type { FilterStore } from "@/stores/createFilterStore"
import { ConnectionIndicator } from "./ConnectionIndicator"
import { CountrySidePanel } from "./CountrySidePanel"

const MapPane = dynamic(() => import("./MapPane").then((m) => m.MapPane), {
  ssr: false,
  loading: () => <PaneSkeleton label="map" />,
})
const GlobePane = dynamic(() => import("./GlobePane").then((m) => m.GlobePane), {
  ssr: false,
  loading: () => <PaneSkeleton label="globe" />,
})

function PaneSkeleton({ label }: { label: string }) {
  return (
    <div className="grid h-full w-full place-items-center bg-neutral-950">
      <span className="font-mono text-[11px] uppercase tracking-widest text-neutral-700">
        initialising {label}…
      </span>
    </div>
  )
}

function filterSummary(useStore: FilterStore): string {
  const sources = useStore.getState().sources
  const active = SOURCE_FILTERS.filter((f) => sources[f.key])
  if (active.length === SOURCE_FILTERS.length) return "all sources"
  if (active.length === 0) return "none"
  return active.map((f) => f.label.toLowerCase()).join(" + ")
}

export function SplitLayout() {
  const configured = useConfigured()
  const events = useEvents()

  const [leftRailOpen, setLeftRailOpen] = useState(false)
  const [rightRailOpen, setRightRailOpen] = useState(false)
  const [focused, setFocused] = useState<"left" | "right">("left")
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null)
  const [leftCount, setLeftCount] = useState(0)
  const [rightCount, setRightCount] = useState(0)

  // re-render trigger for filter summaries when toggles change
  const [, setTick] = useState(0)
  useEffect(() => {
    const a = useLeftPaneStore.subscribe(() => setTick((t) => t + 1))
    const b = useRightPaneStore.subscribe(() => setTick((t) => t + 1))
    return () => {
      a()
      b()
    }
  }, [])

  // Keyboard shortcuts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return
      if (e.key === "[") {
        setLeftRailOpen((o) => !o)
      } else if (e.key === "]") {
        setRightRailOpen((o) => !o)
      } else if (e.key === " ") {
        e.preventDefault()
        const store = focused === "left" ? useLeftPaneStore : useRightPaneStore
        store.getState().togglePlaying()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [focused])

  const latestTs = events[0]?.occurred_at
  const onSelectCountry = useCallback((iso: string) => setSelectedCountry(iso), [])

  // Recomputed on every render; the subscription above ticks on toggle changes.
  const mapSummary = filterSummary(useLeftPaneStore)
  const globeSummary = filterSummary(useRightPaneStore)

  return (
    <main className="relative h-dvh w-screen overflow-hidden bg-neutral-950 text-neutral-100">
      {!configured && (
        <div className="absolute inset-x-0 top-0 z-50 bg-red-950/90 px-4 py-2 text-center font-mono text-xs text-red-200 backdrop-blur">
          Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
        </div>
      )}

      {/* Top-left logo */}
      <div className="pointer-events-none absolute left-3 top-3 z-30">
        <span className="font-mono text-[11px] font-medium uppercase tracking-[0.25em] text-neutral-100/80">
          OSINT World Monitor
        </span>
        <span className="ml-2 font-mono text-[11px] uppercase tracking-[0.25em] text-emerald-400/90">
          · live
        </span>
      </div>

      {/* Top-right connection */}
      <div className="absolute right-3 top-3 z-30">
        <ConnectionIndicator />
      </div>

      <PanelGroup orientation="horizontal" className="h-full w-full">
        <Panel defaultSize={50} minSize={20}>
          <div
            className="h-full w-full"
            onMouseEnter={() => setFocused("left")}
            onFocusCapture={() => setFocused("left")}
          >
            <MapPane
              useStore={useLeftPaneStore}
              railOpen={leftRailOpen}
              onRailOpenChange={setLeftRailOpen}
              onSelectCountry={onSelectCountry}
              onCount={setLeftCount}
            />
          </div>
        </Panel>

        <PanelResizeHandle className="group relative w-px bg-neutral-800 outline-none">
          <span className="absolute inset-y-0 -left-1 -right-1 z-30 transition-colors group-data-[resize-handle-state=drag]:bg-emerald-500/20 group-data-[resize-handle-state=hover]:bg-emerald-500/10" />
          <span className="absolute left-1/2 top-1/2 z-30 h-8 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-neutral-700 transition-colors group-hover:bg-emerald-500" />
        </PanelResizeHandle>

        <Panel defaultSize={50} minSize={20}>
          <div
            className="relative h-full w-full"
            onMouseEnter={() => setFocused("right")}
            onFocusCapture={() => setFocused("right")}
          >
            <GlobePane
              useStore={useRightPaneStore}
              railOpen={rightRailOpen}
              onRailOpenChange={setRightRailOpen}
              onSelectCountry={onSelectCountry}
              onCount={setRightCount}
            />
            <CountrySidePanel country={selectedCountry} onClose={() => setSelectedCountry(null)} />
          </div>
        </Panel>
      </PanelGroup>

      {/* Bottom-left latest timestamp */}
      <div className="pointer-events-none absolute bottom-[calc(8%+8px)] left-3 z-30 min-h-[16px]">
        {latestTs && (
          <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-500">
            latest · {format(new Date(latestTs), "yyyy-MM-dd HH:mm:ss")}
          </span>
        )}
      </div>

      {/* Bottom-center status bar */}
      <div className="pointer-events-none absolute bottom-[calc(8%+8px)] left-1/2 z-30 -translate-x-1/2">
        <span className="rounded-full border border-neutral-800 bg-neutral-950/80 px-3 py-1 font-mono text-[10px] text-neutral-400 backdrop-blur-sm">
          {leftCount} map · {rightCount} globe events in window
          <span className="mx-2 text-neutral-700">|</span>
          map: {mapSummary}
          <span className="mx-2 text-neutral-700">|</span>
          globe: {globeSummary}
        </span>
      </div>

      {/* Keyboard hint */}
      <div className="pointer-events-none absolute bottom-[calc(8%+8px)] right-3 z-30 hidden sm:block">
        <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-600">
          [ ] rails · space play/pause
        </span>
      </div>
    </main>
  )
}
