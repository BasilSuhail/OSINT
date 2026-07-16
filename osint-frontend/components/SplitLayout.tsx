"use client"

import dynamic from "next/dynamic"
import { useCallback, useEffect, useRef, useState } from "react"
import {
  Panel,
  Group as PanelGroup,
  type PanelImperativeHandle,
  Separator as PanelResizeHandle,
} from "react-resizable-panels"
import { useConfigured } from "@/app/providers"
import type { VisibleEvent } from "@/lib/queries"
import { useMediaQuery } from "@/lib/useMediaQuery"
import { useLeftPaneStore } from "@/stores/leftPaneStore"
import { useRightPaneStore } from "@/stores/rightPaneStore"
import { useRightPaneModeStore } from "@/stores/rightPaneModeStore"
import { useStoryDetailStore } from "@/stores/storyDetailStore"
import { CardDeck, type DeckCard } from "./CardDeck"
import { BriefingPanel } from "./panels/BriefingPanel"
import { StoryDetailCard } from "./panels/StoryDetailCard"
import { CoveragePanel } from "./panels/CoveragePanel"
import { ScoreboardPanel } from "./panels/ScoreboardPanel"
import { SituationPanel } from "./panels/SituationPanel"
import { StoriesPanel } from "./panels/StoriesPanel"
import { SystemStatusBar } from "./SystemStatusBar"

const MapPane = dynamic(() => import("./MapPane").then((m) => m.MapPane), {
  ssr: false,
  loading: () => <PaneSkeleton label="map" />,
})
const RightPane = dynamic(() => import("./RightPane").then((m) => m.RightPane), {
  ssr: false,
  loading: () => <PaneSkeleton label="status" />,
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
  const [, setLeftCount] = useState(0)
  const [, setRightCount] = useState(0)

  // Selections drive the right pane's entity-lock mode (#252). The clicked
  // event id also expands its hazard footprint on the map.
  //: Story pop-out (#448): a second card left of the deck, same width.
  const storyDetailOpen = useStoryDetailStore((s) => s.storyId !== null)
  const deckPanelRef = useRef<PanelImperativeHandle | null>(null)

  //: The pop-out mounts at EXACTLY the deck's current width — read the deck's
  //: size in the render that inserts the panel; the map absorbs the difference.
  let deckWidthPct = 30
  try {
    const size = deckPanelRef.current?.getSize()
    if (size && size.asPercentage > 0) deckWidthPct = size.asPercentage
  } catch {
    // deck not laid out yet — first paint; the default is fine
  }
  const entity = useRightPaneModeStore((s) => s.entity)
  const openCountry = useRightPaneModeStore((s) => s.openCountry)
  const openEvent = useRightPaneModeStore((s) => s.openEvent)
  const selectedEventId = entity?.kind === "event" ? entity.event.id : null

  // Keyboard shortcuts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      //: Esc closes the story pop-out from anywhere, even while typing.
      if (e.key === "Escape") {
        useStoryDetailStore.getState().closeStory()
        return
      }
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

  // Selecting anything locks the right pane to that entity; on the narrow
  // single-column layout, reveal the right pane so the detail is visible.
  const onSelectCountry = useCallback(
    (iso: string) => {
      openCountry(iso)
      if (isNarrow) setActivePane("right")
    },
    [openCountry, isNarrow],
  )
  const onSelectEvent = useCallback(
    (ev: VisibleEvent) => {
      openEvent(ev)
      if (isNarrow) setActivePane("right")
    },
    [openEvent, isNarrow],
  )

  // The right pane as a card deck (#328): console keeps its world-status /
  // entity surface, the globe rides as its own lazy card (WebGL mounts on
  // first visit, then stays warm and pauses while off-screen), and the
  // analytical pages fill the rest.
  const deckCards: DeckCard[] = [
    //: fill — the panel is its own scroll surface (live list + transcript) with
    //: a fixed ask-box footer; the deck's non-fill outer scroll would defeat it.
    { key: "situation", title: "situation", fill: true, content: <SituationPanel /> },
    { key: "briefing", title: "briefing", content: <BriefingPanel /> },
    { key: "console", title: "console", fill: true, content: <RightPane /> },
    {
      key: "globe",
      title: "globe",
      fill: true,
      lazy: true,
      content: (isActive: boolean) => (
        <GlobePane
          useStore={useRightPaneStore}
          railOpen={rightRailOpen}
          onRailOpenChange={setRightRailOpen}
          onCount={setRightCount}
          onSelectEvent={onSelectEvent}
          active={isActive}
        />
      ),
    },
    { key: "stories", title: "stories", content: <StoriesPanel /> },
    { key: "scoreboard", title: "scoreboard", content: <ScoreboardPanel /> },
    { key: "coverage", title: "coverage", content: <CoveragePanel /> },
  ]

  return (
    <main className="relative h-dvh w-full overflow-hidden bg-neutral-950 text-neutral-100">
      <SystemStatusBar />
      <div className="relative h-[calc(100dvh-2rem)] w-full overflow-hidden">
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
                  {p === "left" ? "map" : "panel"}
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
                onSelectEvent={onSelectEvent}
                selectedEventId={selectedEventId}
              />
            </div>
            <div
              className="relative h-full w-full"
              style={{ display: activePane === "right" ? "block" : "none" }}
              onMouseEnter={() => setFocused("right")}
            >
              {storyDetailOpen ? <StoryDetailCard /> : <CardDeck cards={deckCards} />}
            </div>
          </div>
        ) : (
          <PanelGroup orientation="horizontal" className="h-full w-full">
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
                  onSelectEvent={onSelectEvent}
                  selectedEventId={selectedEventId}
                />
              </div>
            </Panel>

            <PanelResizeHandle className="group relative w-px bg-neutral-800 outline-none">
              <span className="absolute inset-y-0 -left-1 -right-1 z-30 transition-colors group-data-[resize-handle-state=drag]:bg-emerald-500/20 group-data-[resize-handle-state=hover]:bg-emerald-500/10" />
              <span className="absolute left-1/2 top-1/2 z-30 h-8 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-neutral-700 transition-colors group-hover:bg-emerald-500" />
            </PanelResizeHandle>

            {storyDetailOpen ? (
              <>
                <Panel id="story-detail" defaultSize={deckWidthPct} minSize={12}>
                  <div className="h-full w-full overflow-hidden rounded-2xl border border-neutral-800 bg-neutral-900/40 p-0">
                    <StoryDetailCard />
                  </div>
                </Panel>
                <PanelResizeHandle className="group relative w-px bg-neutral-800 outline-none">
                  <span className="absolute inset-y-0 -left-1 -right-1 z-30 transition-colors group-data-[resize-handle-state=drag]:bg-emerald-500/20 group-data-[resize-handle-state=hover]:bg-emerald-500/10" />
                  <span className="absolute left-1/2 top-1/2 z-30 h-8 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-neutral-700 transition-colors group-hover:bg-emerald-500" />
                </PanelResizeHandle>
              </>
            ) : null}

            <Panel id="deck" panelRef={deckPanelRef} defaultSize={30} minSize={12}>
              <div
                className="relative h-full w-full"
                onMouseEnter={() => setFocused("right")}
                onFocusCapture={() => setFocused("right")}
              >
                <CardDeck cards={deckCards} />
              </div>
            </Panel>
          </PanelGroup>
        )}
      </div>
    </main>
  )
}
