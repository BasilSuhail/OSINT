"use client"

import { ChevronLeft, ChevronRight } from "lucide-react"
import dynamic from "next/dynamic"
import { useCallback, useEffect, useState } from "react"
import { useConfigured } from "@/app/providers"
import type { VisibleEvent } from "@/lib/queries"
import { useMediaQuery } from "@/lib/useMediaQuery"
import { useLeftPaneStore } from "@/stores/leftPaneStore"
import { useRightPaneModeStore } from "@/stores/rightPaneModeStore"
import { useStoryDetailStore } from "@/stores/storyDetailStore"
import { CardDeck, type DeckCard } from "./CardDeck"
import { FloatingPanel } from "./FloatingPanel"
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

/** Deck and detail share one width so the pop-out lines up with the deck
 *  without measuring anything at runtime (#503). */
const PANEL_WIDTH = "clamp(320px, 28vw, 460px)"

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
  const [activePane, setActivePane] = useState<"left" | "right">("left")
  const [, setLeftCount] = useState(0)
  //: Transient "let me see the map" gesture, not a stored preference (#503).
  const [deckCollapsed, setDeckCollapsed] = useState(false)

  // Selections drive the right pane's entity-lock mode (#252). The clicked
  // event id also expands its hazard footprint on the map.
  //: Story pop-out (#448): a second card left of the deck, same width.
  const storyDetailOpen = useStoryDetailStore((s) => s.storyId !== null)
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
        //: `]` used to toggle the right rail, which left with the globe (#494).
        setDeckCollapsed((c) => !c)
      } else if (e.key === " ") {
        e.preventDefault()
        //: The map is the only scrubbable surface now that the globe is gone.
        useLeftPaneStore.getState().togglePlaying()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

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
  // entity surface and the analytical pages fill the rest. The globe card was
  // removed in #494 — its WebGL context was the tab's largest memory holder.
  const deckCards: DeckCard[] = [
    //: fill — the panel is its own scroll surface (live list + transcript) with
    //: a fixed ask-box footer; the deck's non-fill outer scroll would defeat it.
    { key: "situation", title: "situation", fill: true, content: <SituationPanel /> },
    { key: "briefing", title: "briefing", content: <BriefingPanel /> },
    { key: "console", title: "console", fill: true, content: <RightPane /> },
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
                  onClick={() => setActivePane(p)}
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

            <div className="absolute inset-0 z-0">
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
              className="absolute inset-x-2 bottom-2 top-20 z-30"
              style={{ display: activePane === "right" ? "block" : "none" }}
            >
              <FloatingPanel className="h-full w-full">
                {storyDetailOpen ? <StoryDetailCard /> : <CardDeck cards={deckCards} />}
              </FloatingPanel>
            </div>
          </div>
        ) : (
          //: Layered stage (#503): the map is the base layer and fills the
          //: viewport; everything else floats above it. No panel group, no
          //: resize handle — those are what made the console read as boxed.
          <div
            className="relative h-full w-full"
            //: Total width occupied by floating panels on the left edge,
            //: published to descendants so map-level overlays (the scrubber)
            //: stop short of them instead of sliding underneath. Counts the
            //: detail card too when it is open, and collapses to 0 with the deck.
            style={
              {
                "--panel-width": deckCollapsed
                  ? "0px"
                  : storyDetailOpen
                    ? `calc(${PANEL_WIDTH} * 2 + 0.5rem)`
                    : PANEL_WIDTH,
              } as React.CSSProperties
            }
          >
            <div className="absolute inset-0 z-0">
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

            {/* With a fixed deck width the pop-out's position is arithmetic
             *  rather than plumbing the panel's measured pixels. */}
            {storyDetailOpen && !deckCollapsed ? (
              <FloatingPanel
                className="absolute bottom-3 top-3 z-30"
                style={{ width: PANEL_WIDTH, left: `calc(${PANEL_WIDTH} + 1.25rem)` }}
              >
                <StoryDetailCard />
              </FloatingPanel>
            ) : null}

            {/* Collapse handle rides the outer edge of whatever is showing,
             *  tracked by --panel-width. It cannot live inside the deck: that
             *  header row already has the card title on the left and the expand
             *  control on the right. */}
            <button
              type="button"
              onClick={() => setDeckCollapsed((c) => !c)}
              title={deckCollapsed ? "Show panel (])" : "Hide panel (])"}
              style={{ left: `calc(var(--panel-width) + 1rem)` }}
              className="absolute top-1/2 z-30 -translate-y-1/2 rounded-l-md rounded-r-xl border border-white/10 bg-neutral-950/85 px-1.5 py-6 text-neutral-400 shadow-2xl shadow-black/60 backdrop-blur-xl transition-colors hover:text-neutral-100"
            >
              {deckCollapsed ? (
                <ChevronRight size={16} aria-hidden />
              ) : (
                <ChevronLeft size={16} aria-hidden />
              )}
              <span className="sr-only">{deckCollapsed ? "Show panel" : "Hide panel"}</span>
            </button>

            {deckCollapsed ? null : (
              <FloatingPanel
                className="absolute bottom-3 left-3 top-3 z-30"
                style={{ width: PANEL_WIDTH }}
              >
                <CardDeck cards={deckCards} />
              </FloatingPanel>
            )}
          </div>
        )}
      </div>
    </main>
  )
}
