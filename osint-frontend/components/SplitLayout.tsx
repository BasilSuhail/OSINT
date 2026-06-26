"use client"

import dynamic from "next/dynamic"
import { useCallback, useEffect, useState } from "react"
import { format } from "date-fns"
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from "react-resizable-panels"
import { useConfigured, useEvents } from "@/app/providers"
import { SOURCE_FILTERS } from "@/lib/types"
import type { VisibleEvent } from "@/lib/queries"
import { useMediaQuery } from "@/lib/useMediaQuery"
import { useLeftPaneStore } from "@/stores/leftPaneStore"
import { useRightPaneStore } from "@/stores/rightPaneStore"
import type { FilterStore } from "@/stores/createFilterStore"
import { ConnectionIndicator } from "./ConnectionIndicator"
import { CountrySidePanel } from "./CountrySidePanel"
import { DashboardSection } from "./DashboardSection"
import { DetailOverlay } from "./DetailOverlay"
import { EventDetailCard } from "./EventDetailCard"

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
  const isNarrow = useMediaQuery("(max-width: 900px)")

  const [leftRailOpen, setLeftRailOpen] = useState(false)
  const [rightRailOpen, setRightRailOpen] = useState(false)
  const [focused, setFocused] = useState<"left" | "right">("left")
  const [activePane, setActivePane] = useState<"left" | "right">("left")
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null)
  const [selectedEvent, setSelectedEvent] = useState<VisibleEvent | null>(null)
  // Separator position as a % of the viewport, so detail overlays can centre on
  // the divider and follow it as it is dragged (#207). 50 until the first layout.
  const [separatorPct, setSeparatorPct] = useState(50)
  const [leftCount, setLeftCount] = useState(0)
  const [rightCount, setRightCount] = useState(0)
  const overlayPct = isNarrow ? 50 : separatorPct

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
    <main className="relative min-h-dvh w-screen bg-neutral-950 text-neutral-100">
      <div className="relative h-dvh w-full overflow-hidden">
      {!configured && (
        <div className="absolute inset-x-0 top-0 z-50 bg-red-950/90 px-4 py-2 text-center font-mono text-xs text-red-200 backdrop-blur">
          Local API unreachable — start it at NEXT_PUBLIC_API_URL (default http://localhost:8000)
        </div>
      )}

      {/* Top-left logo */}
      <div className={`pointer-events-none absolute left-14 top-3 z-30 transition-opacity ${leftRailOpen ? "opacity-0" : "opacity-100"}`}>
        <span className="font-mono text-[11px] font-medium uppercase tracking-[0.25em] text-neutral-100/80">
          OSINT World Monitor
        </span>
        <span className="ml-2 font-mono text-[11px] uppercase tracking-[0.25em] text-emerald-400/90">
          · live
        </span>
      </div>

      {/* Top-right connection */}
      <div className={`absolute right-14 top-3 z-30 transition-opacity ${rightRailOpen ? "opacity-0 pointer-events-none" : "opacity-100"}`}>
        <ConnectionIndicator />
      </div>

      {isNarrow ? (
        <div className="relative h-full w-full">
          {/* Top tab swap: single pane on phones / narrow tablets. */}
          <div className="pointer-events-auto absolute left-1/2 top-12 z-40 -translate-x-1/2 flex gap-1 rounded-full border border-neutral-800 bg-neutral-950/80 p-1 backdrop-blur-sm">
            {(["left", "right"] as const).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => {
                  setActivePane(p)
                  setFocused(p)
                }}
                className={
                  "rounded-full px-3 py-1 font-mono text-[10px] uppercase tracking-widest transition-colors " +
                  (activePane === p
                    ? "bg-neutral-800 text-neutral-100"
                    : "text-neutral-500 hover:text-neutral-300")
                }
              >
                {p === "left" ? "map" : "globe"}
              </button>
            ))}
          </div>

          <div
            className="h-full w-full"
            style={{ display: activePane === "left" ? "block" : "none" }}
            onMouseEnter={() => setFocused("left")}
          >
            <MapPane
              useStore={useLeftPaneStore}
              railOpen={leftRailOpen}
              onRailOpenChange={setLeftRailOpen}
              onSelectCountry={onSelectCountry}
              onCount={setLeftCount}
              onSelectEvent={setSelectedEvent}
              selectedEventId={selectedEvent?.id ?? null}
            />
          </div>
          <div
            className="relative h-full w-full"
            style={{ display: activePane === "right" ? "block" : "none" }}
            onMouseEnter={() => setFocused("right")}
          >
            <GlobePane
              useStore={useRightPaneStore}
              railOpen={rightRailOpen}
              onRailOpenChange={setRightRailOpen}
              onCount={setRightCount}
              onSelectEvent={setSelectedEvent}
            />
          </div>
          <CountrySidePanel country={selectedCountry} onClose={() => setSelectedCountry(null)} />
        </div>
      ) : (
        <PanelGroup
          orientation="horizontal"
          className="h-full w-full"
          onLayoutChange={(layout: Record<string, number>) => {
            const pct = layout["map"]
            if (typeof pct === "number") setSeparatorPct(pct)
          }}
        >
          <Panel id="map" defaultSize={50} minSize={20}>
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
                onSelectEvent={setSelectedEvent}
                selectedEventId={selectedEvent?.id ?? null}
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
                onCount={setRightCount}
                onSelectEvent={setSelectedEvent}
              />
              <CountrySidePanel
                country={selectedCountry}
                onClose={() => setSelectedCountry(null)}
              />
            </div>
          </Panel>
        </PanelGroup>
      )}

      {/* Event detail — centred on the split separator, follows it as it drags.
          Map + globe stay live behind it (#207). */}
      <DetailOverlay open={!!selectedEvent} leftPct={overlayPct}>
        {selectedEvent && (
          <EventDetailCard
            event={selectedEvent}
            onSelectCountry={onSelectCountry}
            onClose={() => setSelectedEvent(null)}
            embedded
          />
        )}
      </DetailOverlay>

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
      </div>

      {/* Scroll-down dashboard section */}
      <DashboardSection configured={configured} />
    </main>
  )
}
