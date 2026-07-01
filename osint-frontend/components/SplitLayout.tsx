"use client"

import dynamic from "next/dynamic"
import { useCallback, useEffect, useState } from "react"
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from "react-resizable-panels"
import { useConfigured } from "@/app/providers"
import type { VisibleEvent } from "@/lib/queries"
import { useMediaQuery } from "@/lib/useMediaQuery"
import { useLeftPaneStore } from "@/stores/leftPaneStore"
import { useRightPaneStore } from "@/stores/rightPaneStore"
import { CountrySidePanel } from "./CountrySidePanel"
import { DashboardSection } from "./DashboardSection"
import { DetailOverlay } from "./DetailOverlay"
import { EventDetailCard } from "./EventDetailCard"
import { SystemStatusBar } from "./SystemStatusBar"

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

export function SplitLayout() {
  const configured = useConfigured()
  const isNarrow = useMediaQuery("(max-width: 900px)")

  const [leftRailOpen, setLeftRailOpen] = useState(false)
  const [rightRailOpen, setRightRailOpen] = useState(false)
  const [focused, setFocused] = useState<"left" | "right">("left")
  const [activePane, setActivePane] = useState<"left" | "right">("left")
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null)
  const [selectedEvent, setSelectedEvent] = useState<VisibleEvent | null>(null)
  // Separator position as a % of the viewport, so detail overlays can centre on
  // the divider and follow it as it is dragged (#207). 50 until the first layout.
  const [separatorPct, setSeparatorPct] = useState(70)
  const [, setLeftCount] = useState(0)
  const [, setRightCount] = useState(0)
  const overlayPct = isNarrow ? 50 : separatorPct

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
      } else if (e.key === "Escape") {
        setSelectedCountry(null)
        setSelectedEvent(null)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [focused])

  const onSelectCountry = useCallback((iso: string) => setSelectedCountry(iso), [])

  return (
    <main className="relative min-h-dvh w-full overflow-hidden bg-neutral-950 text-neutral-100">
      <SystemStatusBar />
      <div className="relative h-[calc(100dvh-1.75rem)] w-full overflow-hidden">
        {!configured && (
          <div className="absolute inset-x-0 top-0 z-50 bg-red-950/90 px-4 py-2 text-center font-mono text-xs text-red-200 backdrop-blur">
            Local API unreachable - start it at NEXT_PUBLIC_API_URL (default http://localhost:8000)
          </div>
        )}

        {isNarrow ? (
          <div className="relative h-full w-full">
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
            <Panel id="map" defaultSize={70} minSize={20}>
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

            <Panel defaultSize={30} minSize={12}>
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

        {/* Country overview — same centred overlay, offset down so it can coexist
            with an open event card. */}
        <DetailOverlay open={!!selectedCountry} leftPct={overlayPct}>
          <CountrySidePanel country={selectedCountry} onClose={() => setSelectedCountry(null)} />
        </DetailOverlay>
      </div>

      <div>
        {/* Scroll-down dashboard section */}
        <DashboardSection configured={configured} />
      </div>
    </main>
  )
}
